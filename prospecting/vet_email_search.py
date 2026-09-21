#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca mirata email — studi veterinari e cliniche veterinarie per regione.

Cerca su OpenStreetMap (Overpass API, licenza ODbL) tutti gli studi veterinari
e le cliniche veterinarie di una regione italiana, ne estrae gli indirizzi email
e arricchisce le schede senza email leggendo la pagina ufficiale dello studio
(homepage + pagina contatti), sempre da fonti pubbliche e dichiarate.

Fasi:
  1. OSM: interroga Overpass sull'intera regione (o per province, per risposte
     piu' piccole) con la sola ricetta veterinaria
     (amenity=veterinary, healthcare=veterinary). Le categorie senza tag OSM
     standard non vengono cercate: nessuno scraping di directory con termini
     d'uso restrittivi.
  2. Raffina la categoria per parole chiave del nome: Cliniche veterinarie,
     Ospedali veterinari, Ambulatori veterinari ("studi"), Veterinari (generico).
  3. Merge in prospecting/candidates/archive.json con gli stessi 5 controlli
     anti-duplicato dell'H24 (riuso di find_candidates.Archive): mai
     sovrascritture, solo integrazione dei contatti mancanti. La coda H24
     (progress.json) NON viene toccata.
  4. Arricchimento web (solo siti ufficiali delle schede): per ogni studio
     della regione con sito ma senza email, scarica homepage ed eventuale
     pagina contatti ed estrae le email pubblicate. Ogni email arricchita
     riporta l'URL della pagina in cui e' stata trovata.
  5. Output dedicati in prospecting/output/:
     <regione>_vet_emails.csv (una riga per email) e <regione>_vet_all.json.

Uso (dalla root del repo):
  python3 prospecting/vet_email_search.py                          # Piemonte, tutto
  python3 prospecting/vet_email_search.py --region Lombardia
  python3 prospecting/vet_email_search.py --region Piemonte --no-enrich-web
  python3 prospecting/vet_email_search.py --overpass-data a.json b.json
  python3 prospecting/vet_email_search.py --enrich-data enrich.json
  python3 prospecting/vet_email_search.py --dry-run                # nessun salvataggio

Dopo la ricerca, rigenera il database unificato con:
  python3 prospecting/process.py

Dipendenze: solo libreria standard Python 3.8+.
"""

import argparse
import csv
import datetime
import html as html_module
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import find_candidates as fc  # riuso: Archive, element_to_record, load/save, norm_email

ARCHIVE_PATH = os.path.join(BASE, "candidates", "archive.json")
VET_SEARCH_DIR = os.path.join(BASE, "candidates", "vet_search")
QUEUE_PATH = os.path.join(BASE, "queue", "cities.json")
OUT_DIR = os.path.join(BASE, "output")
RUN_LOG_PATH = os.path.join(BASE, "state", "run_log.md")

VET_CATEGORIES = ["Veterinari", "Cliniche veterinarie",
                  "Ambulatori veterinari", "Ospedali veterinari"]

# Province (relazioni admin_level=6 OSM) per le regioni supportate in split.
# Altre regioni: ricerca sull'intero confine regionale (admin_level=4).
PROVINCES_BY_REGION = {
    "Piemonte": ["Torino", "Alessandria", "Asti", "Biella",
                 "Cuneo", "Novara", "Verbano-Cusio-Ossola", "Vercelli"],
}

OVERPASS_TIMEOUT_S = 180
PAGE_TIMEOUT_S = 12
MAX_PAGES_PER_SITE = 2

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAILTO_RE = re.compile(r'mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})',
                       re.IGNORECASE)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
BAD_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js",
            "map", "json", "xml", "pdf", "zip", "woff", "woff2", "ttf", "eot"}
BAD_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply",
              "mailer-daemon", "postmaster"}
BAD_DOMAINS = {"example.com", "example.it", "example.org", "email.com",
               "domain.com", "tuodominio.it", "sentry.io"}
PREFERRED_LOCALS = ("info", "contatti", "contact", "contacts", "segreteria",
                    "studio", "ambulatorio", "clinica", "amministrazione",
                    "direzione", "hello", "mail", "urp", "accettazione")


# --------------------------------------------------------------------------
# Query Overpass
# --------------------------------------------------------------------------

def build_area_query(area_selector):
    """Query veterinaria su un'area OSM (regione o provincia)."""
    body = ("node[\"amenity\"=\"veterinary\"](area);"
            "way[\"amenity\"=\"veterinary\"](area);"
            "node[\"healthcare\"=\"veterinary\"](area);"
            "way[\"healthcare\"=\"veterinary\"](area);")
    return (f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];"
            f"{area_selector};map_to_area;({body});out tags center qt 5000;")


def region_selector(region, admin_level=4):
    safe = region.replace('"', "")
    return (f"rel[\"boundary\"=\"administrative\"][\"admin_level\"=\"{admin_level}\"]"
            f"[\"name\"=\"{safe}\"]")


def overpass_fetch(query, log=print):
    """POST con rotazione endpoint (come l'H24, ma con timeout da query regionale)."""
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(fc.MAX_RETRIES + 1):
        endpoint = fc.ENDPOINTS[attempt % len(fc.ENDPOINTS)]
        try:
            req = urllib.request.Request(
                endpoint, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "PetNote-Prospecting-VetSearch/1.0 (contact: repo owner)"},
                method="POST")
            with urllib.request.urlopen(req, timeout=OVERPASS_TIMEOUT_S + 10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, OSError) as exc:
            last = exc
            wait = min(45, 10 * (attempt + 1))
            log(f"    Overpass errore ({exc}) da {endpoint}: riprovo tra {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Overpass non raggiungibile: {last}")


# --------------------------------------------------------------------------
# Categorie: studi veterinari / cliniche veterinarie
# --------------------------------------------------------------------------

def refine_vet_category(name, tags):
    """amenity=veterinary -> categoria canonica per parole chiave del nome."""
    t = f"{name or ''} {tags.get('healthcare:speciality') or ''} " \
        f"{tags.get('amenity') or ''}".lower()
    if re.search(r"ospedal|hospital|tierklinik.*not|pronto soccorso", t):
        return "Ospedali veterinari"
    if re.search(r"clinic|klinik", t):
        return "Cliniche veterinarie"
    if re.search(r"ambulator|poliambulator|studio\b|studi\b", t):
        return "Ambulatori veterinari"
    return "Veterinari"


def city_from_tags(tags):
    for k in ("addr:city", "addr:town", "addr:village", "addr:suburb",
              "addr:hamlet"):
        if tags.get(k):
            return str(tags[k]).strip()
    return None


def records_from_elements(elements, region, queue_by_city):
    """Elementi OSM -> schede (citta' dai tag addr:*, provincia da coda ISTAT)."""
    records = []
    for el in elements:
        tags = el.get("tags") or {}
        city_name = city_from_tags(tags)
        qc = queue_by_city.get((city_name or "").lower()) if city_name else None
        pseudo_city = {"name": city_name or f"{region} (comune da confermare)",
                       "sigla": qc["sigla"] if qc else None,
                       "region": region}
        rec = fc.element_to_record(el, pseudo_city)
        if rec:
            rec["cat"] = refine_vet_category(rec["n"], tags)
            records.append(rec)
    return records


# --------------------------------------------------------------------------
# Merge in archivio (stessi 5 controlli dell'H24)
# --------------------------------------------------------------------------

def merge_records(records, archive, run_id, log=print):
    stats = {"new": 0, "enrich": 0, "dups": 0}
    for rec in records:
        idx, control = archive.find(rec)
        if idx is None:
            rec["_archive_id"] = len(archive.rows) + 1
            rec["_found_at"] = fc.utc_now()
            rec["_wave"] = run_id
            archive.add(rec)
            stats["new"] += 1
        else:
            stats["dups"] += 1
            changed = archive.enrich(idx, rec)
            if changed:
                archive.rows[idx]["_updated_at"] = fc.utc_now()
                stats["enrich"] += 1
    return stats


# --------------------------------------------------------------------------
# Arricchimento email dai siti ufficiali
# --------------------------------------------------------------------------

def clean_email(raw):
    if not raw:
        return None
    e = str(raw).strip().lower().rstrip(".,;:!?")
    if "@" not in e or " " in e or len(e) > 100:
        return None
    local, _, domain = e.partition("@")
    if not local or not domain or "." not in domain:
        return None
    if local in BAD_LOCALS or domain in BAD_DOMAINS:
        return None
    if domain.rsplit(".", 1)[-1] in BAD_TLDS:
        return None
    if not EMAIL_RE.fullmatch(e):
        return None
    return e


def deobfuscate(text):
    t = html_module.unescape(text)
    t = re.sub(r"\s*\[?\(?(?:at|AT)\)?\]?\s*", "@", t)
    t = re.sub(r"\s*\[?\(?(?:dot|DOT)\)?\]?\s*", ".", t)
    return t


def extract_emails(text, source_url):
    """Testo/HTML -> {email: source_url}. Prima i mailto:, poi testo deoffuscato."""
    found = {}
    if not text:
        return found
    for m in MAILTO_RE.finditer(text):
        e = clean_email(m.group(1))
        if e and e not in found:
            found[e] = source_url
    for m in EMAIL_RE.finditer(deobfuscate(text)):
        e = clean_email(m.group(0))
        if e and e not in found:
            found[e] = source_url
    return found


def pick_best(emails, site_domain):
    """Preferisce il dominio del sito, poi locali 'info/contatti/...', poi i piu' corti."""
    def rank(e):
        local, _, domain = e.partition("@")
        same = 0 if domain == site_domain else 1
        try:
            pref = PREFERRED_LOCALS.index(local)
        except ValueError:
            pref = len(PREFERRED_LOCALS)
        return (same, pref, len(e))
    cands = sorted(set(emails), key=rank)
    return cands[0] if cands else None


def fetch_page(url, timeout=PAGE_TIMEOUT_S):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "PetNote-Prospecting-VetSearch/1.0 "
                                        "(B2B contact enrichment; repo owner)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                return None, None
            raw = resp.read(1_500_000)
        charset = "utf-8"
        m = re.search(r"charset=([\w\-]+)", ctype)
        if m:
            charset = m.group(1)
        return resp.geturl(), raw.decode(charset, errors="ignore")
    except Exception:
        return None, None


def contact_page_url(page_html, base_url, site_domain):
    if not page_html:
        return None
    for m in HREF_RE.finditer(page_html):
        href = m.group(1).strip()
        low = href.lower()
        if "conta" in low or low.rstrip("/").endswith("contact"):
            absu = urllib.parse.urljoin(base_url, href)
            if fc.site_key(absu) == site_domain:
                return absu
    return None


def enrich_record_from_texts(rec, texts, log=print):
    """texts: [(page_url, testo)]. Applica la migliore email trovata. Ritorna email o None."""
    if rec.get("email"):
        return rec["email"]
    site_domain = fc.site_key(rec.get("site"))
    if not site_domain:
        return None
    found = {}
    for page_url, text in texts:
        found.update(extract_emails(text, page_url))
    if not found:
        return None
    best = pick_best(found.keys(), site_domain)
    if not best:
        return None
    rec["email"] = best
    rec["_email_source"] = found[best]
    others = sorted(set(found) - {best})
    note = (f"Email trovata sul sito ufficiale ({found[best]}): verificare "
            f"prima di un eventuale contatto.")
    if others:
        note += f" Altre email sulla pagina: {', '.join(others[:5])}."
    rec["notes"] = ((rec.get("notes") or "") + " ⧉ " + note).strip(" ⧉")
    rec["_updated_at"] = fc.utc_now()
    return best


def enrich_from_web(records, delay=1.5, max_sites=None, log=print):
    """Arricchimento via rete: scarica homepage (+ pagina contatti) dei siti ufficiali."""
    stats = {"sites": 0, "with_email": 0, "pages": 0}
    targets = [r for r in records if r.get("site") and not r.get("email")]
    if max_sites:
        targets = targets[:max_sites]
    for i, rec in enumerate(targets):
        site = rec["site"] if str(rec["site"]).lower().startswith("http") \
            else "https://" + str(rec["site"]).strip()
        domain = fc.site_key(site)
        log(f"    [{i + 1}/{len(targets)}] {rec.get('n')} <{domain}>")
        stats["sites"] += 1
        texts = []
        final_url, page = fetch_page(site)
        stats["pages"] += 1
        time.sleep(delay)
        if page:
            texts.append((final_url or site, page))
            contact_url = contact_page_url(page, final_url or site, domain)
            if contact_url and len(texts) < MAX_PAGES_PER_SITE:
                c_url, c_page = fetch_page(contact_url)
                stats["pages"] += 1
                time.sleep(delay)
                if c_page:
                    texts.append((c_url or contact_url, c_page))
        email = enrich_record_from_texts(rec, texts, log)
        if email:
            stats["with_email"] += 1
            log(f"      -> {email}")
    return stats


def enrich_from_data(records, enrich_entries, log=print):
    """Arricchimento offline: testi gia' scaricati ({site, source_url, text})."""
    by_domain = {}
    for e in enrich_entries:
        d = fc.site_key(e.get("site") or e.get("source_url"))
        if d:
            by_domain.setdefault(d, []).append((e.get("source_url"), e.get("text") or ""))
    stats = {"sites": 0, "with_email": 0, "pages": 0}
    for rec in records:
        if rec.get("email") or not rec.get("site"):
            continue
        texts = by_domain.get(fc.site_key(rec["site"]))
        if not texts:
            continue
        stats["sites"] += 1
        stats["pages"] += len(texts)
        if enrich_record_from_texts(rec, texts, log):
            stats["with_email"] += 1
    return stats


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


CSV_COLS = ["email", "business_name", "category", "city", "province", "region",
            "address", "phone", "website", "contact_name", "email_source",
            "provenienza", "source", "source_url"]


def write_outputs(region, vet_records, log=print):
    os.makedirs(OUT_DIR, exist_ok=True)
    base = f"{slug(region)}_vet"
    with_email = [r for r in vet_records if r.get("email")]
    csv_path = os.path.join(OUT_DIR, base + "_emails.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS, delimiter=";")
        w.writeheader()
        for r in sorted(with_email,
                        key=lambda x: ((x.get("city") or ""), (x.get("n") or ""))):
            for addr in re.split(r"[;,\s]+", str(r["email"]).strip()):
                addr = addr.strip().lower()
                if not addr:
                    continue
                w.writerow({
                    "email": addr,
                    "business_name": r.get("n") or "",
                    "category": r.get("cat") or "",
                    "city": (r.get("city") or "").split(" (")[0],
                    "province": r.get("prov") or "",
                    "region": r.get("reg") or "",
                    "address": r.get("addr") or "",
                    "phone": r.get("tel") or "",
                    "website": r.get("site") or "",
                    "contact_name": r.get("contact") or "",
                    "email_source": r.get("_email_source") or "tag OSM (email/contact:email)",
                    "provenienza": "automatica",
                    "source": r.get("src") or "",
                    "source_url": r.get("srcurl") or "",
                })
    json_path = os.path.join(OUT_DIR, base + "_all.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(vet_records, fh, ensure_ascii=False, indent=2)
    log(f"  CSV email: {csv_path} ({len(with_email)} schede con email)")
    log(f"  JSON completo: {json_path} ({len(vet_records)} schede vet)")
    return csv_path, json_path


def append_log(region, run_id, stats, log=print):
    lines = ["",
             f"## Ricerca mirata vet ({region}) — {fc.utc_now()} ({run_id})",
             f"Studi veterinari e cliniche veterinarie in {region}: "
             f"{stats.get('elements', 0)} elementi OSM, "
             f"{stats.get('records', 0)} schede candidate, "
             f"{stats.get('new', 0)} nuove in archivio, "
             f"{stats.get('enrich', 0)} integrate da OSM, "
             f"{stats.get('web_sites', 0)} siti visitati, "
             f"{stats.get('web_emails', 0)} email trovate sui siti ufficiali, "
             f"{stats.get('vet_total', 0)} schede vet in regione "
             f"({stats.get('vet_with_email', 0)} con email).",
             ""]
    if stats.get("failed"):
        lines.append("Aree fallite: " + ", ".join(stats["failed"]))
        lines.append("")
    with open(RUN_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def load_queue_by_city():
    queue = fc.load_json(QUEUE_PATH, [])
    return {c["name"].lower(): c for c in queue}, queue


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="Piemonte",
                    help="regione da cercare (default: Piemonte)")
    ap.add_argument("--single-area", action="store_true",
                    help="una sola query regionale invece dello split per province")
    ap.add_argument("--overpass-data", nargs="*", default=None,
                    help="file JSON Overpass gia' scaricati (nessuna rete per OSM)")
    ap.add_argument("--no-enrich-web", action="store_true",
                    help="salta l'arricchimento dai siti ufficiali")
    ap.add_argument("--enrich-only", action="store_true",
                    help="solo arricchimento web delle schede vet in archivio "
                         "(salta ricerca OSM e merge)")
    ap.add_argument("--enrich-data", default=None,
                    help="file JSON con testi gia' scaricati [{site, source_url, text}]")
    ap.add_argument("--max-sites", type=int, default=200,
                    help="tetto siti da visitare (default 200)")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="pausa tra richieste web in secondi (default 1.5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="non salva nulla (archivio, output, log)")
    args = ap.parse_args()

    region = args.region.strip()
    run_id = "vet_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Ricerca mirata vet — regione: {region} ({run_id})")

    queue_by_city, _queue = load_queue_by_city()
    archive_rows = fc.load_json(ARCHIVE_PATH, [])
    archive = fc.Archive(archive_rows)
    print(f"Archivio: {len(archive_rows)} schede")

    # --- 1) OSM ---
    elements = []
    failed = []
    if args.enrich_only:
        print("  modalita' --enrich-only: salto ricerca OSM e merge")
    if args.enrich_only:
        records = []
        stats = {"elements": 0, "records": 0, "failed": [], "new": 0,
                 "enrich": 0, "dups": 0}
    elif args.overpass_data:
        for path in args.overpass_data:
            data = fc.load_json(path, {})
            elements.extend(data.get("elements", []))
            print(f"  offline {path}: {len(data.get('elements', []))} elementi")
    else:
        areas = [(region, 4)]
        if not args.single_area and region in PROVINCES_BY_REGION:
            areas = [(p, 6) for p in PROVINCES_BY_REGION[region]]
        for name, level in areas:
            q = build_area_query(region_selector(name, level))
            print(f"  Overpass [{name}]: interrogazione...")
            try:
                if args.dry_run:
                    print(f"    [dry-run] {q}")
                    continue
                resp = overpass_fetch(q)
                n = len(resp.get("elements", []))
                print(f"    {n} elementi")
                elements.extend(resp.get("elements", []))
            except Exception as exc:
                print(f"    ERRORE area {name}: {exc}")
                failed.append(name)
            time.sleep(fc.MIN_DELAY)
    seen, uniq = set(), []
    for el in elements:
        k = (el.get("type"), el.get("id"))
        if k not in seen:
            seen.add(k)
            uniq.append(el)
    print(f"Elementi OSM unici: {len(uniq)}")

    records = records_from_elements(uniq, region, queue_by_city)
    cats = {}
    for r in records:
        cats[r["cat"]] = cats.get(r["cat"], 0) + 1
    print(f"Schede candidate: {len(records)} {cats}")

    stats = {"elements": len(uniq), "records": len(records), "failed": failed}

    # --- 2) merge ---
    mstats = merge_records(records, archive, run_id)
    stats.update(mstats)
    print(f"Merge: {mstats['new']} nuove, {mstats['enrich']} integrate, "
          f"{mstats['dups']} gia' note")

    # --- 3) arricchimento web (solo schede vet della regione) ---
    vet_records = [r for r in archive.rows
                   if (r.get("reg") or "") == region and r.get("cat") in VET_CATEGORIES]
    print(f"Schede vet in {region} (archivio): {len(vet_records)}")
    if args.no_enrich_web:
        print("Arricchimento web saltato (--no-enrich-web)")
        stats.update({"web_sites": 0, "web_emails": 0})
    elif args.enrich_data:
        entries = fc.load_json(args.enrich_data, [])
        wstats = enrich_from_data(vet_records, entries)
        stats.update({"web_sites": wstats["sites"], "web_emails": wstats["with_email"]})
        print(f"Arricchimento offline: {wstats['sites']} siti, "
              f"{wstats['with_email']} nuove email")
    elif not args.dry_run:
        wstats = enrich_from_web(vet_records, delay=args.delay,
                                 max_sites=args.max_sites)
        stats.update({"web_sites": wstats["sites"], "web_emails": wstats["with_email"]})
        print(f"Arricchimento web: {wstats['sites']} siti visitati "
              f"({wstats['pages']} pagine), {wstats['with_email']} nuove email")
    else:
        stats.update({"web_sites": 0, "web_emails": 0})

    vet_with_email = sum(1 for r in vet_records if r.get("email"))
    stats.update({"vet_total": len(vet_records), "vet_with_email": vet_with_email})
    print(f"Vet in {region}: {len(vet_records)} schede, {vet_with_email} con email")

    # --- 4) persistenza (mai la coda H24) ---
    if args.dry_run:
        print("[dry-run] nessun salvataggio.")
        return 0
    run_dir = os.path.join(VET_SEARCH_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, f"{slug(region)}.json"), "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    fc.save_json(ARCHIVE_PATH, archive_rows)
    write_outputs(region, vet_records)
    append_log(region, run_id, stats)
    print("Archivio, output e diario aggiornati. Rigenera il database con:")
    print("  python3 prospecting/process.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
