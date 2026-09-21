#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraping mirato PagineGialle — veterinari per comune.

Raccoglie le schede "veterinari" di PagineGialle (nome, indirizzo, telefoni,
sito web, URL scheda) per i comuni richiesti e le fonde in
prospecting/candidates/archive.json con gli stessi 5 controlli anti-duplicato
dell'H24 (mai sovrascritture, solo integrazione dei contatti mancanti).
Le email non sono esposte da PagineGialle (usa form "Scrivici"): dopo lo
scraping, estrarle dai siti ufficiali con:
  python3 prospecting/vet_email_search.py --region <Regione> --enrich-only

AVVISO LEGALE / ToS: PagineGialle vieta l'estrazione automatizzata nei suoi
termini e robots.txt (Disallow: /ricerca/). Lo script PARTE SOLO con il flag
--accept-tos-risk (l'operatore si assume la responsabilita'), usa ritardi
educati tra le richieste (default 4s + jitter), un comune alla volta, e si
ferma al primo blocco HTTP 403/429. Volumi consigliati: pochi comuni al giorno.

Uso (dalla root del repo, serve rete):
  python3 prospecting/scrape_paginegialle.py --accept-tos-risk --cities "Torino"
  python3 prospecting/scrape_paginegialle.py --accept-tos-risk --region Piemonte
  python3 prospecting/scrape_paginegialle.py --accept-tos-risk --region Piemonte --details
  python3 prospecting/scrape_paginegialle.py --self-test     # nessun rete
  python3 prospecting/scrape_paginegialle.py --dry-run ...   # nessun salvataggio

Dopo lo scraping, rigenera il database con:
  python3 prospecting/process.py

Dipendenze: solo libreria standard Python 3.8+.
"""

import argparse
import datetime
import html as html_module
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import find_candidates as fc
import vet_email_search as ves

ARCHIVE_PATH = os.path.join(BASE, "candidates", "archive.json")
PG_DIR = os.path.join(BASE, "candidates", "pg_search")
QUEUE_PATH = os.path.join(BASE, "queue", "cities.json")
RUN_LOG_PATH = os.path.join(BASE, "state", "run_log.md")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SEARCH_URL = "https://www.paginegialle.it/ricerca/{query}/{city}"
PAGE_PATTERNS = ["?p={n}", "/p-{n}", "?pag={n}"]


# --------------------------------------------------------------------------
# HTTP educato
# --------------------------------------------------------------------------

class Fetch:
    def __init__(self, delay=4.0, timeout=30, log=print):
        self.delay = delay
        self.timeout = timeout
        self.log = log
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor())
        self.opener.addheaders = [("User-Agent", UA),
                                  ("Accept-Language", "it-IT,it;q=0.9")]

    def get(self, url):
        time.sleep(self.delay + random.uniform(0, self.delay / 2))
        try:
            with self.opener.open(url, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return None
                raw = resp.read(3_000_000)
                return raw.decode("utf-8", errors="ignore"), resp.geturl()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise RuntimeError(f"blocco anti-bot HTTP {exc.code} su {url}: "
                                   f"fermati e riprova tra ore/giorni, volumi minori.")
            self.log(f"    HTTP {exc.code} su {url}")
            return None
        except Exception as exc:
            self.log(f"    errore rete su {url}: {exc}")
            return None


# --------------------------------------------------------------------------
# Parsing (JSON-LD prima, euristiche poi)
# --------------------------------------------------------------------------

LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
                   r"(.*?)</script>", re.IGNORECASE | re.DOTALL)
MAILTO_RE = re.compile(r'mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})',
                       re.IGNORECASE)
TEL_RE = re.compile(r'href=["\']tel:([^"\']+)["\']', re.IGNORECASE)
DETAIL_RE = re.compile(r'href=["\'](https://www\.paginegialle\.it/[^"\']+)["\']',
                       re.IGNORECASE)


def walk_ld(node, out):
    if isinstance(node, dict):
        t = str(node.get("@type", ""))
        if "Business" in t or t in ("VeterinaryCare", "Organization",
                                   "LocalBusiness", "HealthAndBeautyBusiness"):
            out.append(node)
        for v in node.values():
            walk_ld(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_ld(v, out)


def parse_ld_json(page_html):
    """Estrae schede dai blocchi JSON-LD. Ritorna lista di dict grezzi."""
    recs = []
    for m in LD_RE.finditer(page_html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        found = []
        walk_ld(data, found)
        for b in found:
            addr = b.get("address") or {}
            if isinstance(addr, str):
                addr = {"streetAddress": addr}
            tels = b.get("telephone")
            if isinstance(tels, str):
                tels = [tels]
            recs.append({
                "name": b.get("name"),
                "tel": ", ".join(t for t in (tels or []) if t) or None,
                "street": addr.get("streetAddress"),
                "zip": addr.get("postalCode"),
                "city": addr.get("addressLocality"),
                "site": b.get("url"),
                "detail": b.get("@id") or b.get("url"),
            })
    # dedup per nome
    seen, uniq = set(), []
    for r in recs:
        k = (r.get("name") or "").lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def parse_cards_fallback(page_html, city_query):
    """Euristica su link schede + dintorni (se JSON-LD assente)."""
    if not page_html:
        return []
    recs = []
    for m in DETAIL_RE.finditer(page_html):
        url = m.group(1).split("?")[0].rstrip("/")
        if "/ricerca/" in url or "/mappa/" in url or "/magazine/" in url:
            continue
        window = page_html[max(0, m.start() - 1500):m.start() + 1500]
        text = re.sub(r"<[^>]+>", " ", window)
        text = html_module.unescape(re.sub(r"\s+", " ", text))
        # telefoni nel riquadro
        tels = []
        for t in TEL_RE.finditer(window):
            num = re.sub(r"[^\d+ ]", "", t.group(1)).strip()
            if num and num not in tels:
                tels.append(num)
        # indirizzo "Via X, 1 - 10100 Citta' (TO)"
        addr_m = re.search(r"((?:Via|Corso|Piazza|Largo|Strada|Viale|Localit[aà]|"
                           r"Frazione| Lungo)[^,]{0,60},\s*\S+)\s*-\s*"
                           r"(\d{5})\s*([A-Za-zÀ-ÿ' ]+?)\s*\(([A-Z]{2})\)", text)
        name_m = re.search(r"([A-ZÀ-Þ][^|<>]{3,80}?)\s*(?:Veterinaria|\(?\d+\)?)",
                           text)
        recs.append({
            "name": name_m.group(1).strip() if name_m else None,
            "tel": ", ".join(tels) or None,
            "street": addr_m.group(1).strip() if addr_m else None,
            "zip": addr_m.group(2) if addr_m else None,
            "city": addr_m.group(3).strip() if addr_m else city_query,
            "site": None,
            "detail": url,
        })
    # dedup per scheda
    seen, uniq = set(), []
    for r in recs:
        if r["detail"] not in seen:
            seen.add(r["detail"])
            uniq.append(r)
    return uniq


def find_sub_queries(page_html):
    """Link 'cerca per quartiere' / 'nelle vicinanze' (paginazione robusta)."""
    out = []
    if not page_html:
        return out
    for m in re.finditer(r'href=["\'](/ricerca/[^"\']+)["\']', page_html):
        path = m.group(1)
        if path not in out:
            out.append(path)
    return out


def parse_detail(page_html):
    """Scheda dettaglio -> {email, site, tels, piva}. Le email sono rare
    (PG usa form 'Scrivici'), ma se c'e' un mailto lo prendiamo."""
    d = {"email": None, "site": None, "tels": [], "piva": None}
    if not page_html:
        return d
    for m in MAILTO_RE.finditer(page_html):
        e = ves.clean_email(m.group(1))
        if e and "italiaonline" not in e:
            d["email"] = e
            break
    for m in re.finditer(r'href=["\'](https?://(?!www\.paginegialle\.it|wa\.me)'
                         r'[^"\']+)["\'][^>]{0,200}>\s*Sito web', page_html):
        d["site"] = m.group(1)
        break
    for t in TEL_RE.finditer(page_html):
        num = re.sub(r"[^\d+ ]", "", t.group(1)).strip()
        if num and num not in d["tels"] and "1240" not in num:
            d["tels"].append(num)
    m = re.search(r"P\.?\s*IVA:?\s*(\d{11})", page_html)
    if m:
        d["piva"] = m.group(1)
    return d


# --------------------------------------------------------------------------
# Record pipeline
# --------------------------------------------------------------------------

def to_record(g, city_query, prov, region):
    name = (g.get("name") or "").strip()
    if not name:
        return None
    street = (g.get("street") or "").strip()
    addr = ", ".join(x for x in [street, g.get("zip")] if x) or None
    city = (g.get("city") or city_query or "").strip() or city_query
    notes = ("Fonte PagineGialle: verificare prima di un eventuale contatto.")
    return {
        "n": name,
        "cat": ves.refine_vet_category(name, {}),
        "sub": None,
        "city": city,
        "prov": prov,
        "reg": region,
        "addr": addr,
        "site": g.get("site") or None,
        "email": g.get("email") or None,
        "tel": g.get("tel") or None,
        "ig": None,
        "fb": None,
        "contact": None,
        "src": "PagineGialle",
        "srcurl": g.get("detail"),
        "osm_id": None,
        "osm_type": None,
        "lat": None,
        "lon": None,
        "other": f"P.IVA {g['piva']}" if g.get("piva") else "directory",
        "notes": notes,
        "_system": "automatica",
    }


# --------------------------------------------------------------------------
# Scrape per comune
# --------------------------------------------------------------------------

def scrape_city(city, query, fetcher, args, log=print):
    base = SEARCH_URL.format(query=urllib.parse.quote(query),
                             city=urllib.parse.quote(city))
    log(f"  {base}")
    got = fetcher.get(base)
    if not got:
        return [], []
    page_html, _final = got
    recs = parse_ld_json(page_html)
    method = "json-ld"
    if not recs:
        recs = parse_cards_fallback(page_html, city)
        method = "euristica"
    log(f"    batch 1: {len(recs)} schede ({method})")

    # tentativi di paginazione classica (?p=2, /p-2, ?pag=2)
    seen_details = {r.get("detail") for r in recs if r.get("detail")}
    for n in range(2, args.max_pages + 1):
        grown = False
        for pat in PAGE_PATTERNS:
            url = base + pat.format(n=n)
            got = fetcher.get(url)
            if not got:
                continue
            more = parse_ld_json(got[0]) or parse_cards_fallback(got[0], city)
            fresh = [r for r in more if r.get("detail") not in seen_details]
            if fresh:
                log(f"    batch {n} ({pat.format(n=n)}): +{len(fresh)} schede")
                recs.extend(fresh)
                seen_details.update(r.get("detail") for r in fresh
                                    if r.get("detail"))
                grown = True
                break
        if not grown:
            break

    # sotto-query (quartieri / vicinanze) come paginazione robusta
    sub_urls = []
    if args.sub_queries:
        for path in find_sub_queries(page_html):
            if path.startswith("/ricerca/") and len(sub_urls) < args.max_sub:
                sub_urls.append("https://www.paginegialle.it" + path)
    for url in sub_urls:
        got = fetcher.get(url)
        if not got:
            continue
        more = parse_ld_json(got[0]) or parse_cards_fallback(got[0], city)
        fresh = [r for r in more if r.get("detail") not in seen_details]
        if fresh:
            log(f"    sotto-query {url.split('/ricerca/')[-1][:60]}: +{len(fresh)}")
            recs.extend(fresh)
            seen_details.update(r.get("detail") for r in fresh
                                if r.get("detail"))
    return recs, sub_urls


# --------------------------------------------------------------------------
# Self-test (nessuna rete)
# --------------------------------------------------------------------------

SAMPLE_LD = """
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
{"@type":"VeterinaryCare","name":"Clinica Veterinaria Test",
 "telephone":"+39 011 111111",
 "address":{"streetAddress":"Via Roma 1","postalCode":"10100",
            "addressLocality":"Torino"},
 "url":"https://www.clinicatest.it",
 "@id":"https://www.paginegialle.it/clinica-test"}]}
</script>"""


def self_test():
    recs = parse_ld_json(SAMPLE_LD)
    assert len(recs) == 1, recs
    r = to_record({**recs[0], "email": None, "piva": None}, "Torino", "TO",
                  "Piemonte")
    assert r["n"] == "Clinica Veterinaria Test"
    assert r["cat"] == "Cliniche veterinarie", r["cat"]
    assert r["tel"] == "+39 011 111111"
    assert r["city"] == "Torino" and r["prov"] == "TO"
    d = parse_detail('<a href="mailto:info@clinicatest.it">x</a> P. IVA: 01234567890')
    assert d["email"] == "info@clinicatest.it" and d["piva"] == "01234567890"
    assert ves.clean_email("a@b.png") is None
    print("self-test OK (json-ld, record pipeline, detail, email)")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cities", help="comuni separati da virgola")
    ap.add_argument("--region", help="tutti i comuni in coda di questa regione")
    ap.add_argument("--query", default="veterinari")
    ap.add_argument("--details", action="store_true",
                    help="visita anche le schede dettaglio (lento, raramente aggiunge email)")
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--max-sub", type=int, default=12,
                    help="max sotto-query (quartieri/vicinanze) per comune")
    ap.add_argument("--no-sub-queries", dest="sub_queries", action="store_false")
    ap.add_argument("--delay", type=float, default=4.0)
    ap.add_argument("--max-cities", type=int, default=0,
                    help="fermati dopo N comuni (0 = tutti)")
    ap.add_argument("--resume", action="store_true",
                    help="salta i comuni gia' scaricati in staging")
    ap.add_argument("--accept-tos-risk", action="store_true",
                    help="REQUIRED: dichiari di assumerti la responsabilita' ToS/robots")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test() or 0

    if not args.accept_tos_risk:
        print("BLOCCATO: PagineGialle vieta lo scraping (ToS + robots Disallow: /ricerca/).")
        print("Rilancia con --accept-tos-risk solo se te ne assumi la responsabilita',")
        print("con volumi educati (pochi comuni al giorno) e nel rispetto dei contatti B2B.")
        return 2

    queue = fc.load_json(QUEUE_PATH, [])
    if args.cities:
        names = [s.strip() for s in args.cities.split(",") if s.strip()]
        by_name = {c["name"].lower(): c for c in queue}
        cities = []
        for n in names:
            c = by_name.get(n.lower())
            cities.append(c or {"name": n, "sigla": None, "region": None})
    elif args.region:
        cities = [c for c in queue if (c.get("region") or "") == args.region]
        if not cities:
            print(f"Nessun comune in coda per regione '{args.region}'")
            return 2
    else:
        print("Specifica --cities o --region (v. --help)")
        return 2
    if args.max_cities:
        cities = cities[:args.max_cities]

    run_id = "pg_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Scraping PagineGialle '{args.query}' — {len(cities)} comuni ({run_id})")
    print("Avviso: ToS/robots accettati dall'operatore; delay educato "
          f"{args.delay}s+r jitter, stop a 403/429.")

    archive = fc.Archive(fc.load_json(ARCHIVE_PATH, []))
    fetcher = Fetch(delay=args.delay)
    run_dir = os.path.join(PG_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    stats = {"cities": 0, "cards": 0, "records": 0, "new": 0, "enrich": 0,
             "dups": 0, "failed": []}

    for i, city in enumerate(cities):
        cname = city["name"]
        stage = os.path.join(run_dir, cname + ".json")
        print(f"\n[{i + 1}/{len(cities)}] {cname}")
        try:
            if args.resume and os.path.exists(stage):
                print("    gia' in staging (--resume): ricarico")
                recs = json.load(open(stage, encoding="utf-8"))
            else:
                if args.dry_run:
                    print(f"    [dry-run] {SEARCH_URL.format(query=args.query, city=cname)}")
                    continue
                cards, _subs = scrape_city(cname, args.query, fetcher, args)
                stats["cards"] += len(cards)
                recs = []
                for g in cards:
                    if args.details and g.get("detail", "").startswith("http"):
                        got = fetcher.get(g["detail"])
                        if got:
                            d = parse_detail(got[0])
                            g["email"] = d["email"]
                            g["site"] = g["site"] or d["site"]
                            if d["tels"]:
                                g["tel"] = g["tel"] or ", ".join(d["tels"])
                            g["piva"] = d["piva"]
                            if d["email"]:
                                g["_email_source"] = got[1]
                    r = to_record(g, cname, city.get("sigla"),
                                  city.get("region") or args.region)
                    if r:
                        if g.get("_email_source"):
                            r["_email_source"] = g["_email_source"]
                        recs.append(r)
                json.dump(recs, open(stage, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
        except RuntimeError as exc:
            print(f"    STOP: {exc}")
            stats["failed"].append(cname)
            break
        except Exception as exc:
            print(f"    ERRORE: {exc}")
            stats["failed"].append(cname)
            continue
        stats["cities"] += 1
        stats["records"] += len(recs)
        new_c, rich_c, dup_c = 0, 0, 0
        for rec in recs:
            idx, _control = archive.find(rec)
            if idx is None:
                rec["_archive_id"] = len(archive.rows) + 1
                rec["_found_at"] = fc.utc_now()
                rec["_wave"] = run_id
                archive.add(rec)
                new_c += 1
            else:
                dup_c += 1
                if archive.enrich(idx, rec):
                    archive.rows[idx]["_updated_at"] = fc.utc_now()
                    rich_c += 1
        stats["new"] += new_c
        stats["enrich"] += rich_c
        stats["dups"] += dup_c
        print(f"    schede {len(recs)} | NUOVE {new_c} | gia' note {dup_c} "
              f"(integrate {rich_c})")

    if not args.dry_run:
        fc.save_json(ARCHIVE_PATH, archive.rows)
        with open(RUN_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n## Scraping PagineGialle '%s' — %s (%s)\n"
                     "%d comuni ok, %d schede web, %d schede candidate, "
                     "%d nuove in archivio, %d integrate, %d fallite%s.\n\n" % (
                         args.query, fc.utc_now(), run_id, stats["cities"],
                         stats["cards"], stats["records"], stats["new"],
                         stats["enrich"], len(stats["failed"]),
                         (": " + ", ".join(stats["failed"])) if stats["failed"] else ""))
    print("\n=== BILANCIO ===")
    print(f"comuni: {stats['cities']} (falliti: {len(stats['failed'])}) | "
          f"schede web: {stats['cards']} | candidate: {stats['records']}")
    print(f"NUOVE in archivio: {stats['new']} | gia' note: {stats['dups']} "
          f"(integrate: {stats['enrich']}) | archivio totale: {len(archive.rows)}")
    print("Rigenera il database con: python3 prospecting/process.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
