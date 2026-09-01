#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PetNote Prospecting — Ricerca automatica H24 (OpenStreetMap / Overpass API)

Cosa fa, in un giro:
  1. prende le prossime `cities_per_run` citta' dalla coda
     prospecting/queue/cities.json (388 comuni, dati ISTAT);
  2. per ogni citta' risolve il centro amministrativo (ref:ISTAT del comune)
     e interroga Overpass sui confini del comune per le categorie della
     "ricetta" (solo OpenStreetMap, licenza ODbL: nessuno scraping di
     directory con termini d'uso restrittivi);
  3. converte gli elementi OSM in schede nel formato grezzo della pipeline;
  4. anti-duplicato su 5 controlli (id oggetto, email, telefono, sito,
     nome+citta' anche simile) contro TUTTO l'archivio (manuale + automatico);
     se la scheda esiste gia' ma il candidato ha contatti nuovi, li integra
     senza creare duplicati;
  5. salva: schede grezze in prospecting/candidates/runs/, archivio unico
     prospecting/candidates/archive.json, aggiorna la coda (lat/lon),
     prospecting/state/run_log.md e prospecting/state/progress.json.
  Lo scoring/output avviene dopo con: python3 prospecting/process.py

Uso:
  python3 prospecting/find_candidates.py                     # batch da config (6)
  python3 prospecting/find_candidates.py --batch 2
  python3 prospecting/find_candidates.py --cities "Roma,Milano"
  python3 prospecting/find_candidates.py --list-done
  python3 prospecting/find_candidates.py --reset-progress   # nuovo ciclo (riparte da 0)
  python3 prospecting/find_candidates.py --dry-run           # mostra le query, non interroga
  python3 prospecting/find_candidates.py --offline-fixture FILE  # test senza rete

Dipendenze: solo libreria standard Python 3.8+.
"""

import argparse
import datetime
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "config.json")
QUEUE_PATH = os.path.join(BASE, "queue", "cities.json")
ARCHIVE_PATH = os.path.join(BASE, "candidates", "archive.json")
RUNS_DIR = os.path.join(BASE, "candidates", "runs")
STATE_DIR = os.path.join(BASE, "state")
PROGRESS_PATH = os.path.join(STATE_DIR, "progress.json")
RUN_LOG_PATH = os.path.join(STATE_DIR, "run_log.md")

CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}
OPS = CFG.get("overpass", {})
# Endpoint di fallback: i config possono specificarne una parte, ma i default
# vengono sempre aggiunti (dedup, ordine preservato) per massimizzare la resilienza.
DEFAULT_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
ENDPOINTS = list(dict.fromkeys((OPS.get("endpoints") or []) + DEFAULT_ENDPOINTS))
TIMEOUT = int(OPS.get("timeout_s", 60))
MIN_DELAY = float(OPS.get("min_delay_s", 1.5))
MAX_RETRIES = int(OPS.get("max_retries", 3))
MAX_ELEM = int(OPS.get("max_elements_per_city", 1500))
RADIUS_RULES = sorted(
    ((int(r[0]), int(r[1])) for r in OPS.get("radius_by_population", []) if len(r) == 2),
    reverse=True,
)
DEFAULT_RADIUS = int(OPS.get("default_radius_m", 5000))
DEFAULT_RECIPE = [
    {"category": "Veterinari", "queries": [{"amenity": "veterinary"},
                                            {"healthcare": "veterinary"}]},
    {"category": "Pet shop", "queries": [{"shop": "pet"}]},
    {"category": "Toelettature", "queries": [{"shop": "pet_grooming"},
                                             {"shop": "grooming"}]},
    {"category": "Pensioni per animali", "queries": [{"amenity": "animal_boarding"}]},
    {"category": "Canili", "queries": [{"amenity": "animal_shelter", "shelter_type": "dog"}]},
    {"category": "Rifugi per animali", "queries": [{"amenity": "animal_shelter"}]},
    {"category": "Allevamenti professionali",
     "queries": [{"amenity": "animal_breeding", "breed": "*"}]},
    {"category": "Allevatori", "queries": [{"amenity": "animal_breeding"}]},
]
RECIPE = OPS.get("recipe") or DEFAULT_RECIPE
CITIES_PER_RUN = int(CFG.get("cities_per_run", 6))
OVERRIDE_CITIES = None  # impostato da --cities


# --------------------------------------------------------------------------
# Helper di normalizzazione (allineati a process.py)
# --------------------------------------------------------------------------

def norm_email(e):
    if not e:
        return None
    e = str(e).strip().lower()
    return e if ("@" in e and " " not in e) else None


def norm_site(site):
    if not site:
        return None
    s = str(site).strip()
    if not s.lower().startswith("http"):
        s = "https://" + s
    return s


def site_key(site):
    s = norm_site(site)
    if not s:
        return None
    s = re.sub(r"^https?://", "", s.lower())
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/").split("/")[0]


def phone_digits(tel):
    if not tel:
        return []
    out = []
    for p in re.split(r"[,;/]", str(tel)):
        d = re.sub(r"\D", "", p)
        if d:
            out.append(d)
    return out


_STOP = {"di", "del", "della", "delle", "dei", "da", "d", "il", "la", "lo", "i",
         "le", "gli", "e", "s", "a", "snc", "srl", "sas", "ssd", "arl", "asd",
         "odv", "onlus", "ambulatorio", "veterinario", "veterinaria", "centro",
         "rifugio", "pet", "dog", "zampa", "cani", "gatti", "dr", "dott",
         "dottssa", "ssa", "ss", "l"}


def name_tokens(n):
    n = re.sub(r"[^a-zàèéìòù'0-9 ]", " ", str(n).lower())
    return set(t for t in n.split() if t not in _STOP and len(t) > 1)


def similar_names(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    ratio = difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()
    return inter >= 2 or ratio > 0.72


def norm_name(n):
    """Identita' nome per il controllo 5: minuscolo, token distintivi ordinati."""
    toks = sorted(name_tokens(n))
    return " ".join(toks) if toks else re.sub(r"\s+", " ", str(n).lower().strip())


# --------------------------------------------------------------------------
# Stato: coda, archivio, progresso
# --------------------------------------------------------------------------

def load_json(path, default):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Archive:
    """Archivio unico (manuale + automatico): verita' anti-duplicato."""

    def __init__(self, rows):
        self.rows = rows
        self.by_osm = {}
        self.by_email = {}
        self.by_site = {}
        self.by_phone = {}
        self.by_namecity = {}  # city -> [(norm_name, idx)]
        for i, r in enumerate(rows):
            self._index(i, r)

    @staticmethod
    def _name_of(r):
        return r.get("n") or r.get("business_name") or ""

    def _index(self, i, r):
        if r.get("osm_id") is not None and r.get("osm_type"):
            self.by_osm[(str(r["osm_type"]), str(r["osm_id"]))] = i
        e = norm_email(r.get("email"))
        if e:
            self.by_email.setdefault(e, i)
        sk = site_key(r.get("site"))
        if sk:
            self.by_site.setdefault(sk, i)
        for d in phone_digits(r.get("tel")):
            self.by_phone.setdefault(d, i)
        city = (r.get("city") or "").lower()
        if city:
            self.by_namecity.setdefault(city, []).append((norm_name(self._name_of(r)), i))

    def find(self, cand):
        """Ritorna (indice, nome del controllo) del duplicato, altrimenti (None, None)."""
        # 1) ID oggetto OSM
        if cand.get("osm_id") is not None and cand.get("osm_type"):
            k = (str(cand["osm_type"]), str(cand["osm_id"]))
            if k in self.by_osm:
                return self.by_osm[k], "id oggetto OSM"
        # 2) email
        e = norm_email(cand.get("email"))
        if e and e in self.by_email:
            return self.by_email[e], "email"
        # 3) telefono (con verifica nome simile, come process.py)
        for d in phone_digits(cand.get("tel")):
            if d in self.by_phone and similar_names(
                    cand["n"], self._name_of(self.rows[self.by_phone[d]])):
                return self.by_phone[d], "telefono"
        # 4) sito (dominio)
        sk = site_key(cand.get("site"))
        if sk and sk in self.by_site:
            return self.by_site[sk], "sito web"
        # 5) nome + citta' (anche simile)
        city = (cand.get("city") or "").lower()
        if city:
            nc = norm_name(cand["n"])
            for old, i in self.by_namecity.get(city, []):
                if old == nc or similar_names(cand["n"], old):
                    return i, "nome+citta'"
        return None, None

    def add(self, cand):
        i = len(self.rows)
        self.rows.append(cand)
        self._index(i, cand)
        return i

    def enrich(self, i, cand):
        """Riempe SOLO i campi vuoti del record esistente (mai sovrascritture)."""
        r = self.rows[i]
        changed = []
        for k in ("email", "tel", "site", "addr", "contact", "ig", "fb"):
            if not r.get(k) and cand.get(k):
                r[k] = cand[k]
                changed.append(k)
        return changed


# --------------------------------------------------------------------------
# Query Overpass
# --------------------------------------------------------------------------

def build_geocode_queries(code, name):
    """Due query: centro confine per ref:ISTAT, poi per nome."""
    q_code = (f'[out:json][timeout:{TIMEOUT}];'
              f'rel["boundary"="administrative"]["admin_level"="8"]'
              f'["ref:ISTAT"="{code}"];out center qt 1;')
    safe_name = name.replace('"', "")
    q_name = (f'[out:json][timeout:{TIMEOUT}];'
              f'rel["boundary"="administrative"]["admin_level"="8"]'
              f'["name"="{safe_name}"];out center qt 1;')
    return q_code, q_name


def _clauses_for(rule, sel):
    """sel: 'area' oppure 'around:<r>,<lat>,<lon>'. AND dentro una query, OR tra query."""
    clauses = []
    for query in rule.get("queries", []):
        for t in ("node", "way"):
            tag_sel = "".join(
                f'["{k}"]' if v == "*" else f'["{k}"="{v}"]' for k, v in query.items())
            clauses.append(f"{t}{tag_sel}({sel});")
    return clauses


def build_area_query(code, name):
    q_code, __ = build_geocode_queries(code, name)
    body = "".join("".join(_clauses_for(rule, "area")) for rule in RECIPE)
    header = q_code.split(";", 2)[1]  # "rel[...]..."
    return f'[out:json][timeout:{TIMEOUT}];{header};map_to_area;(' + \
           body + f');out body center qt {MAX_ELEM};'


def build_around_query(radius, lat, lon):
    sel = f"around:{radius},{lat},{lon}"
    body = "".join("".join(_clauses_for(rule, sel)) for rule in RECIPE)
    return f'[out:json][timeout:{TIMEOUT}];(' + body + f');out body center qt {MAX_ELEM};'


def overpass_post(query, endpoint, dry_run=False):
    if dry_run:
        print(f"    [dry-run] POST {endpoint}\n    {query}")
        return {"elements": []}
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        endpoint, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "PetNote-Prospecting-H24/1.0 (contact: repo owner)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def overpass_with_retry(query, dry_run=False, log=print):
    """Retry con backoff limitato su una lista di endpoint (rotate).

    Non solleva mai errori di rete "a meta'": se tutti i tentativi falliscono
    solleva RuntimeError (gestito per-citta' da run()), cosi' una citta'
    fallita non ferma mai il giro.
    """
    last = None
    for attempt in range(MAX_RETRIES + 1):
        endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            return overpass_post(query, endpoint, dry_run)
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, OSError) as exc:
            last = exc
            code = getattr(exc, "code", None)
            reason = getattr(exc, "reason", None) or getattr(exc, "msg", None) or type(exc).__name__
            if code == 429:
                wait = min(45, 15 * (attempt + 1))
                log(f"    rate-limit (429) da {endpoint}: attendo {wait}s...")
            elif code in (400, 504):
                wait = min(30, 8 * (attempt + 1))
                log(f"    Overpass {code} ({reason}) da {endpoint}: riprovo tra {wait}s...")
            else:
                wait = min(30, 5 * (attempt + 1))
                log(f"    errore temporaneo ({reason}) da {endpoint}: riprovo tra {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Overpass non raggiungibile dopo {MAX_RETRIES + 1} tentativi: {last}")


# --------------------------------------------------------------------------
# Geocodifica + ricerca per comune
# --------------------------------------------------------------------------

def radius_for(population):
    for thr, rad in RADIUS_RULES:
        if population >= thr:
            return rad
    return DEFAULT_RADIUS


def geocode_city(city, dry_run=False, log=print):
    """Ritorna (lat, lon, metodo) oppure (None, None, None)."""
    if city.get("lat") and city.get("lon"):
        return city["lat"], city["lon"], "cache"
    q_code, q_name = build_geocode_queries(city["code"], city["name"])
    if dry_run:
        print(f"    [dry-run] geocodifica {city['name']} (ref:ISTAT {city['code']}):")
        print(f"      {q_code}")
        print(f"      fallback nome: {q_name}")
        return 43.0, 12.0, "dry-run"
    resp = overpass_with_retry(q_code, dry_run, log)
    elems = [e for e in resp.get("elements", []) if e.get("center")]
    if not elems:
        resp = overpass_with_retry(q_name, dry_run, log)
        elems = [e for e in resp.get("elements", []) if e.get("center")]
    if not elems:
        log(f"    geocodifica fallita per {city['name']} (confine non trovato)")
        return None, None, None
    c = elems[0]["center"]
    return c["lat"], c["lon"], "confine amministrativo"


def _element_latlon(el):
    if el.get("center"):
        return el["center"]["lat"], el["center"]["lon"]
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    return None, None


def _pick_name(tags):
    for k in ("name", "operator:name", "operator", "brand"):
        v = tags.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return None


_CURATED_TAGS = ("amenity", "shop", "healthcare", "shelter_type", "animal",
                 "breed", "opening_hours", "operator:type", "brand")


def element_to_record(el, city):
    """Elemento OSM -> scheda nel formato grezzo della pipeline."""
    tags = el.get("tags") or {}
    name = _pick_name(tags)
    if not name:
        return None  # niente scheda senza nome
    lat, lon = _element_latlon(el)
    category = None
    for rule in RECIPE:
        for query in rule.get("queries", []):
            ok = True
            for k, v in query.items():
                if v == "*":
                    if k not in tags:
                        ok = False
                        break
                elif str(tags.get(k)) != str(v):
                    ok = False
                    break
            if ok:
                category = rule["category"]
                break
        if category:
            break
    if not category:
        return None

    street = " ".join(x for x in [tags.get("addr:street"),
                                  tags.get("addr:housenumber")] if x)
    addr = ", ".join(x for x in [street, tags.get("addr:postcode")] if x)
    site = tags.get("website") or tags.get("contact:website")
    email = tags.get("contact:email") or tags.get("email")
    tel = tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile")
    ig_raw = tags.get("contact:instagram") or tags.get("instagram")
    ig = None
    if ig_raw:
        m = re.search(r"instagram\.com/([A-Za-z0-9_.-]+)", str(ig_raw))
        ig = (m.group(1) if m else str(ig_raw)).lstrip("@")
    fb = tags.get("contact:facebook") or tags.get("facebook")
    curated = {k: v for k, v in tags.items() if k in _CURATED_TAGS and v}
    other = "OSM: " + ", ".join(f"{k}={v}" for k, v in curated.items()) if curated else "OSM"
    notes = ("Fonte OpenStreetMap (ODbL). Dati di contatto come mappati in OSM: "
             "verificare prima di un eventuale contatto.")
    return {
        "n": name,
        "cat": category,
        "sub": None,
        "city": city["name"],
        "prov": city.get("sigla"),
        "reg": city.get("region"),
        "addr": addr or None,
        "site": site or None,
        "email": email or None,
        "tel": tel or None,
        "ig": ig or None,
        "fb": (fb if fb and "http" in str(fb) else None),
        "contact": tags.get("operator") or tags.get("operator:name") or None,
        "src": "OpenStreetMap (Overpass API, ODbL)",
        "srcurl": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
        "osm_id": el["id"],
        "osm_type": el["type"],
        "osm_tags": tags,
        "lat": lat,
        "lon": lon,
        "other": other,
        "notes": notes,
        "_system": "automatica",
    }


def search_city(city, dry_run=False, log=print):
    """Esegue la ricerca per un comune. Ritorna (records, geocode_info)."""
    lat, lon, method = geocode_city(city, dry_run, log)
    if lat is None or lon is None:
        return [], None
    if method != "cache":
        city["lat"], city["lon"] = lat, lon  # cache persistita a fine giro

    q_area = build_area_query(city["code"], city["name"])
    if dry_run:
        print(f"    [dry-run] ricerca {city['name']}:")
        print(f"      {q_area}")
        return [], {"lat": lat, "lon": lon, "method": method}
    try:
        resp = overpass_with_retry(q_area, dry_run, log)
    except RuntimeError as exc:
        log(f"    {exc}; passo al fallback 'around'")
        resp = None
    elems = (resp or {}).get("elements", []) if resp else []
    method_q = "confine (area) + OSM"
    if not elems:
        rad = radius_for(city.get("population") or 0)
        q_around = build_around_query(rad, lat, lon)
        try:
            resp = overpass_with_retry(q_around, dry_run, log)
        except RuntimeError as exc:
            log(f"    fallback fallito: {exc}")
            resp = None
        elems = (resp or {}).get("elements", []) if resp else []
        method_q = f"raggio {rad}m"
    log(f"    {method_q}: {len(elems)} elementi OSM trovati")

    records = []
    for el in elems:
        rec = element_to_record(el, city)
        if rec:
            records.append(rec)
    return records, {"lat": lat, "lon": lon, "method": method}


# --------------------------------------------------------------------------
# Giro
# --------------------------------------------------------------------------

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_cities(queue, progress, batch):
    if OVERRIDE_CITIES:
        return OVERRIDE_CITIES, 0
    done = set(progress.get("done", []))
    remaining = [c for c in queue if c["name"] not in done]
    return remaining[:batch], len(remaining)


def run(log=print, dry_run=False):
    queue = load_json(QUEUE_PATH, [])
    if not queue:
        log("ERRORE: coda non trovata. Rigenerala con prospecting/tools/generate_queue.py")
        return 2
    progress = load_json(PROGRESS_PATH, {"done": [], "last_run": None,
                                         "runs": 0, "new_total": 0, "enrich_total": 0})
    archive = Archive(load_json(ARCHIVE_PATH, []))

    sel, remaining = next_cities(queue, progress, CITIES_PER_RUN)
    if not sel:
        log("Coda completata: tutte le 388 citta' sono state processate. "
            "Per un nuovo ciclo: python3 prospecting/find_candidates.py --reset-progress")
        return 0
    log(f"Giro H24 -> {len(sel)} citta' (rimaste in coda: {remaining}, "
        f"archivio: {len(archive.rows)} schede)")

    run_id = "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(2).hex()
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    log_lines = [f"## Giro del {utc_now()} ({run_id})",
                 "| Citta' | Elementi | Trovati | Nuovi | Gia' noti / integrati | Esito |",
                 "|---|---|---|---|---|---|"]
    stats = {"cities": 0, "elements": 0, "found": 0, "new": 0, "enrich": 0,
             "dups": 0, "failed": [], "done_cities": []}

    t0 = time.time()
    for i, city in enumerate(sel):
        log(f"\n[{i + 1}/{len(sel)}] {city['name']} ({city.get('sigla')})")
        try:
            records, geo = search_city(city, dry_run, log)
        except Exception as exc:  # una citta' non deve fermare il giro
            log(f"    ERRORE: {exc}")
            stats["failed"].append({"name": city["name"], "error": str(exc)})
            log_lines.append(
                f"| {city['name']} | - | - | - | - | ERRORE: {str(exc)[:80]} |")
            continue
        if geo is None:
            stats["failed"].append({"name": city["name"], "error": "geocodifica fallita"})
            log_lines.append(f"| {city['name']} | - | - | - | - | geocodifica fallita |")
            continue
        stats["cities"] += 1
        stats["done_cities"].append(city["name"])
        stats["elements"] += len(records)
        stats["found"] += len(records)

        # dump grezzo della citta' (dati candidati, prima del merge in archivio)
        with open(os.path.join(run_dir, city["name"] + ".json"), "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)

        new_c, rich_c, dup_c = 0, 0, 0
        for rec in records:
            idx, control = archive.find(rec)
            if idx is None:
                rec["_archive_id"] = len(archive.rows) + 1
                rec["_found_at"] = utc_now()
                rec["_wave"] = run_id
                archive.add(rec)
                new_c += 1
            else:
                dup_c += 1
                changed = archive.enrich(idx, rec)
                if changed:
                    archive.rows[idx]["_updated_at"] = utc_now()
                    rich_c += 1
        stats["new"] += new_c
        stats["enrich"] += rich_c
        stats["dups"] += dup_c
        log_lines.append(
            f"| {city['name']} | {len(records)} | {len(records)} | {new_c} | "
            f"{dup_c} ({rich_c} integrati) | ok |")
        log(f"    trovati {len(records)} | NUOVI {new_c} | gia' noti {dup_c} "
            f"(integrati {rich_c})")
        if not dry_run:
            save_json(QUEUE_PATH, queue)
        time.sleep(MIN_DELAY)

    # --- persistenza ---
    # Solo le citta' riuscite vengono marcate come completate: quelle fallite
    # (rate-limit, timeout, geocodifica) verranno ritentate al prossimo giro.
    progress["done"] = sorted(set(progress.get("done", [])) | set(stats["done_cities"]))
    progress["runs"] = int(progress.get("runs", 0)) + 1
    progress["last_run"] = utc_now()
    progress["new_total"] = int(progress.get("new_total", 0)) + stats["new"]
    progress["enrich_total"] = int(progress.get("enrich_total", 0)) + stats["enrich"]
    if not OVERRIDE_CITIES:
        stats["remaining"] = max(0, remaining - len(sel))

    if not dry_run:
        save_json(ARCHIVE_PATH, archive.rows)
        save_json(PROGRESS_PATH, progress)
        save_json(QUEUE_PATH, queue)
        lines = log_lines + [
            "",
            f"**Bilancio**: {stats['cities']} citta' ok, {stats['elements']} elementi OSM, "
            f"{stats['found']} schede candidate, {stats['new']} nuove, "
            f"{stats['enrich']} integrate, {len(stats['failed'])} citta' fallite "
            f"(verranno ritentate), coda rimanente ~{stats.get('remaining', 0)}.",
            "",
        ]
        if stats["failed"]:
            lines.append("**Citta' fallite (ritentate al prossimo giro):**")
            for f in stats["failed"]:
                lines.append(f"- {f['name']}: {f['error']}")
            lines.append("")
        with open(RUN_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    log("\n=== BILANCIO GIRO ===")
    log(f"citta' processate: {stats['cities']}  (fallite: {len(stats['failed'])})")
    log(f"elementi OSM: {stats['elements']} | schede candidate: {stats['found']}")
    log(f"NUOVE in archivio: {stats['new']} | gia' note: {stats['dups']} "
        f"(integrate con nuovi contatti: {stats['enrich']})")
    log(f"archivio totale: {len(archive.rows)} | coda completata: "
        f"{len(progress['done'])}/{len(queue)} | durata: {int(time.time() - t0)}s")
    # Il giro termina SEMPRE con codice 0: i fallimenti per-citta' sono loggati
    # e non devono far fallire il job di GitHub Actions (che salterebbe gli
    # step successivi di rigenerazione e commit dei risultati parziali).
    return 0


# --------------------------------------------------------------------------
# Modalita' offline (fixture) per test riproducibili senza rete
# --------------------------------------------------------------------------

def run_offline(fixture_path):
    fixture = load_json(fixture_path, {})
    responses = fixture.get("responses", {})

    def fake_search(city, dry_run=False, log=print):
        if city.get("lat") is None or city.get("lon") is None:
            city["lat"] = 40.0 + (len(city["name"]) % 10) * 0.01
            city["lon"] = 15.0 + (len(city["name"]) % 10) * 0.01
        resp = responses.get(city["name"])
        if not resp:
            return [], {"lat": city["lat"], "lon": city["lon"], "method": "fixture"}
        records = []
        for el in resp.get("elements", []):
            rec = element_to_record(el, city)
            if rec:
                records.append(rec)
        return records, {"lat": city["lat"], "lon": city["lon"], "method": "fixture"}

    prev_search = globals()["search_city"]
    globals()["search_city"] = fake_search
    try:
        return run()
    finally:
        globals()["search_city"] = prev_search


def main():
    global CITIES_PER_RUN, OVERRIDE_CITIES
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=int, default=None,
                    help=f"numero di citta' in questo giro (default {CITIES_PER_RUN})")
    ap.add_argument("--cities", help="override: nomi di citta' separati da virgola")
    ap.add_argument("--offline-fixture", help="file JSON di prova (nessuna rete)")
    ap.add_argument("--list-done", action="store_true", help="mostra lo stato della coda")
    ap.add_argument("--reset-progress", action="store_true",
                    help="azzera il progresso (nuovo ciclo di 388 citta')")
    ap.add_argument("--dry-run", action="store_true", help="mostra query senza interrogare Overpass")
    args = ap.parse_args()

    if args.batch:
        CITIES_PER_RUN = args.batch

    if args.list_done:
        q = load_json(QUEUE_PATH, [])
        p = load_json(PROGRESS_PATH, {"done": []})
        done = set(p.get("done", []))
        print(f"coda: {len(q)} | completate: {len(done)} | rimanenti: {len(q) - len(done)}")
        for c in q:
            print(("  [x] " if c["name"] in done else "  [ ] ") + c["name"])
        return 0

    if args.reset_progress:
        save_json(PROGRESS_PATH, {"done": [], "last_run": None,
                                  "runs": 0, "new_total": 0, "enrich_total": 0})
        print("Progresso azzerato: il prossimo giro riparte dalla prima citta' in coda.")
        return 0

    if args.cities:
        names = [s.strip() for s in args.cities.split(",") if s.strip()]
        queue = load_json(QUEUE_PATH, [])
        by_name = {c["name"]: c for c in queue}
        sel = [by_name[n] for n in names if n in by_name]
        missing = [n for n in names if n not in by_name]
        if missing:
            print("ATTENZIONE: non in coda:", ", ".join(missing))
        if not sel:
            print("Nessuna citta' valida selezionata")
            return 2
        OVERRIDE_CITIES = sel
        CITIES_PER_RUN = len(sel)

    if args.offline_fixture:
        return run_offline(args.offline_fixture)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
