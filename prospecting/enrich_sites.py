#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PetNote Prospecting — Arricchimento email dai siti ufficiali delle attivita'.

Perche': OpenStreetMap ha molte attivita' con sito web ma senza tag email.
Questo script prende le schede dell'archivio che hanno un sito e nessuna email,
legge SOLO il sito ufficiale della stessa attivita' (home + pagina contatti) e
ne estrae l'indirizzo email pubblicato dall'attivita' stessa.

Cosa NON fa (scelta di compliance, coerente con config.json -> overpass._commento):
  - nessuno scraping di directory (PagineGialle, ecc.) ne' di social network;
  - rispetta robots.txt del sito; User-Agent dichiarato; ritardo tra le pagine;
  - scarica al massimo 3 pagine HTML per sito, ognuna con tetto di dimensione.

Estrazione email (in ordine): JSON-LD schema.org, link mailto:, protezione
Cloudflare (data-cfemail), testo con offuscamenti [at]/(at)/[dot], testo in chiaro.

Uso:
  python3 prospecting/enrich_sites.py                    # budget da config.json
  python3 prospecting/enrich_sites.py --max-sites 50 --max-seconds 300
  python3 prospecting/enrich_sites.py --dry-run          # elenca i siti da visitare
  python3 prospecting/enrich_sites.py --site https://esempio.it   # prova un solo sito

Dopo l'arricchimento: python3 prospecting/process.py

Dipendenze: solo libreria standard Python 3.9+.
"""

import argparse
import concurrent.futures
import datetime
import html as htmllib
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from find_candidates import (ARCHIVE_PATH, CFG, load_json, norm_email,  # noqa: E402
                             norm_site, save_json, site_key, utc_now)

SE_CFG = CFG.get("website_enrichment", {})
USER_AGENT = SE_CFG.get("user_agent",
                        "PetNoteProspectingBot/1.0 (ricerca contatti professionali pubblici)")
MAX_SITES = int(SE_CFG.get("max_sites_per_run", 400))
MAX_SECONDS = int(SE_CFG.get("max_seconds_per_run", 1200))
WORKERS = int(SE_CFG.get("workers", 8))
PAGE_DELAY = float(SE_CFG.get("page_delay_s", 1.0))
FETCH_TIMEOUT = int(SE_CFG.get("fetch_timeout_s", 12))
MAX_PAGE_BYTES = int(SE_CFG.get("max_page_bytes", 600_000))
RECHECK_DAYS = float(SE_CFG.get("recheck_days", 30))
RETRY_ERROR_DAYS = float(SE_CFG.get("retry_error_days", 3))
MAX_PAGES = 3

# link che portano alla pagina contatti
CONTACT_HINT = re.compile(r"contatt|contact|dove-siamo|chi-siamo|about|info|recapit|trovaci", re.I)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}")
# offuscamenti comuni: info [at] dominio [dot] it  /  info(at)dominio.it
OBFUSC_AT = re.compile(r"\s*[\[\(\{]\s*(?:at|chiocciola)\s*[\]\)\}]\s*", re.I)
OBFUSC_DOT = re.compile(r"\s*[\[\(\{]\s*(?:dot|punto)\s*[\]\)\}]\s*", re.I)

JUNK_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".woff", ".woff2")
JUNK_DOMAINS = ("sentry.io", "sentry-next.wixpress.com", "wixpress.com", "example.com",
                "example.org", "domain.com", "yourdomain.com", "email.com", "sentry.wixpress.com",
                "godaddy.com", "wordpress.com", "wordpress.org", "schema.org", "w3.org")
JUNK_LOCAL = ("noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon",
              "postmaster", "abuse", "privacy", "dpo", "gdpr", "webmaster", "nome", "name",
              "yourname", "tuonome", "user", "username", "email", "indirizzo")
FREE_PROVIDERS = {"gmail.com", "hotmail.com", "hotmail.it", "libero.it", "yahoo.it", "yahoo.com",
                  "outlook.com", "outlook.it", "virgilio.it", "alice.it", "tin.it", "live.it",
                  "icloud.com", "tiscali.it", "email.it", "pec.it", "legalmail.it"}


# --------------------------------------------------------------------------
# Estrazione email (funzioni pure, testabili senza rete)
# --------------------------------------------------------------------------

def _cf_decode(hexstr):
    """Decodifica la protezione email di Cloudflare (XOR con il primo byte)."""
    try:
        data = bytes.fromhex(hexstr)
        key = data[0]
        return bytes(b ^ key for b in data[1:]).decode("utf-8", "ignore")
    except (ValueError, IndexError):
        return None


def _valid(email):
    e = norm_email(email)
    if not e:
        return None
    e = e.strip(".,;:<>()[]\"'")
    if not EMAIL_RE.fullmatch(e):
        return None
    local, _, domain = e.partition("@")
    if e.endswith(JUNK_SUFFIX) or any(domain == d or domain.endswith("." + d) for d in JUNK_DOMAINS):
        return None
    if local in JUNK_LOCAL or re.search(r"@\d+x\b", e):
        return None
    return e


def extract_emails(html_text):
    """Ritorna le email del documento HTML, senza duplicati, in ordine di affidabilita'."""
    found = []

    def add(e):
        v = _valid(e)
        if v and v not in found:
            found.append(v)

    # 1) JSON-LD schema.org: campo "email"
    for blob in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>",
                           html_text, re.S | re.I):
        for m in re.finditer(r'"email"\s*:\s*"([^"]+)"', blob):
            add(htmllib.unescape(m.group(1)).replace("mailto:", ""))
    # 2) link mailto:
    for m in re.finditer(r'href\s*=\s*["\']mailto:([^"\'?>\s]+)', html_text, re.I):
        add(urllib.parse.unquote(htmllib.unescape(m.group(1))))
    # 3) Cloudflare email protection
    for m in re.finditer(r'data-cfemail\s*=\s*["\']([0-9a-fA-F]+)["\']', html_text):
        add(_cf_decode(m.group(1)))
    for m in re.finditer(r"/cdn-cgi/l/email-protection#([0-9a-fA-F]+)", html_text):
        add(_cf_decode(m.group(1)))
    # 4) testo visibile: rimuovi tag/script, decodifica entita' e offuscamenti
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmllib.unescape(text)
    text = OBFUSC_DOT.sub(".", OBFUSC_AT.sub("@", text))
    for m in EMAIL_RE.finditer(text):
        add(m.group(0))
    return found


def pick_best(emails, site):
    """Preferisce email sul dominio del sito (piu' affidabili), poi provider non-free."""
    if not emails:
        return None
    key = site_key(site) or ""
    root = ".".join(key.split(".")[-2:]) if key else ""

    def rank(e):
        d = e.split("@")[1]
        if root and (d == root or d.endswith("." + root)):
            return 0
        if d not in FREE_PROVIDERS:
            return 1
        return 2
    return sorted(emails, key=rank)[0]  # sort stabile: a parita' vale l'ordine di apparizione


def contact_links(base_url, html_text):
    """Fino a 2 link interni (stesso host) verso pagine contatti."""
    host = urllib.parse.urlsplit(base_url).netloc.lower().removeprefix("www.")
    out = []
    for m in re.finditer(r'<a\s[^>]*href\s*=\s*["\']([^"\'#]+)["\'][^>]*>(.*?)</a>',
                         html_text, re.S | re.I):
        href, label = htmllib.unescape(m.group(1)), re.sub(r"<[^>]+>", "", m.group(2))
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        if not (CONTACT_HINT.search(href) or CONTACT_HINT.search(label)):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue
        if parts.netloc.lower().removeprefix("www.") != host:
            continue
        if re.search(r"\.(pdf|jpe?g|png|zip|docx?)$", parts.path, re.I):
            continue
        url = urllib.parse.urlunsplit(parts._replace(fragment=""))
        if url not in out and url.rstrip("/") != base_url.rstrip("/"):
            out.append(url)
    # le pagine "contatti" prima di "chi siamo"/"info"
    out.sort(key=lambda u: 0 if re.search(r"contatt|contact", u, re.I) else 1)
    return out[:MAX_PAGES - 1]


# --------------------------------------------------------------------------
# Rete
# --------------------------------------------------------------------------

class Blocked(Exception):
    """Host non visitabile (robots.txt, indirizzo privato, schema non http)."""


def _check_host(url, allow_local=False):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Blocked("schema non valido")
    if allow_local:
        return
    # evita che un sito (o un redirect) punti la richiesta verso la rete interna
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror as exc:
        raise Blocked(f"dns: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise Blocked("indirizzo non pubblico")


def _open(url, allow_local=False):
    _check_host(url, allow_local)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "it,en;q=0.5"})
    return urllib.request.urlopen(req, timeout=FETCH_TIMEOUT)


def fetch_html(url, allow_local=False):
    """Scarica una pagina HTML (tetto di dimensione). Ritorna (url_finale, testo)."""
    with _open(url, allow_local) as resp:
        _check_host(resp.geturl(), allow_local)  # controlla anche il dopo-redirect
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype and "html" not in ctype and "xml" not in ctype:
            raise Blocked(f"contenuto non HTML ({ctype.split(';')[0]})")
        raw = resp.read(MAX_PAGE_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), raw.decode(charset, "replace")


def robots_allows(url, allow_local=False):
    """True se robots.txt consente il nostro User-Agent. Errori di rete => non si visita."""
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        with _open(robots_url, allow_local) as resp:
            rp.parse(resp.read(200_000).decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False  # robots.txt vietato: per la specifica equivale a "tutto vietato"
        return True       # 404 e simili: nessuna restrizione dichiarata
    return rp.can_fetch(USER_AGENT, url)


def check_site(site, allow_local=False, delay=None):
    """Visita il sito di una scheda. Ritorna (email|None, url_pagina|None, esito)."""
    delay = PAGE_DELAY if delay is None else delay
    url = norm_site(site)
    if not url:
        return None, None, "sito non valido"
    try:
        if not robots_allows(url, allow_local):
            return None, None, "robots.txt vieta"
        final, page = fetch_html(url, allow_local)
        queue = [(final, page)]
        visited = {final.rstrip("/")}
        links = contact_links(final, page)
        seen_emails = []
        i = 0
        while i < len(queue):
            u, h = queue[i]
            i += 1
            for e in extract_emails(h):
                if e not in seen_emails:
                    seen_emails.append(e)
            best = pick_best(seen_emails, final)
            # se la home ha gia' un'email sul dominio del sito non servono altre pagine
            if best and best.split("@")[1] not in FREE_PROVIDERS:
                return best, u, "email"
            if i == 1:
                for link in links:
                    if link.rstrip("/") in visited:
                        continue
                    visited.add(link.rstrip("/"))
                    time.sleep(delay)
                    try:
                        if robots_allows(link, allow_local):
                            queue.append(fetch_html(link, allow_local))
                    except (urllib.error.URLError, Blocked, OSError, ValueError):
                        continue
        best = pick_best(seen_emails, final)
        if best:
            return best, queue[-1][0] if len(queue) > 1 else final, "email"
        return None, None, "nessuna email"
    except Blocked as exc:
        return None, None, f"bloccato: {exc}"
    except urllib.error.HTTPError as exc:
        return None, None, f"errore: HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, None, f"errore: {str(exc)[:80]}"


# --------------------------------------------------------------------------
# Selezione delle schede e aggiornamento archivio
# --------------------------------------------------------------------------

def _parse_utc(ts):
    try:
        return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def needs_check(row, now):
    """Scheda con sito e senza email, non controllata di recente."""
    if row.get("email") or not row.get("site"):
        return False
    checked = _parse_utc(row.get("_site_checked_at"))
    if checked is None:
        return True
    age = (now - checked).total_seconds() / 86400
    result = row.get("_site_result") or ""
    limit = RETRY_ERROR_DAYS if result.startswith(("errore", "bloccato")) else RECHECK_DAYS
    return age >= limit


def apply_result(archive_rows, idx, email, page, result):
    """Scrive l'esito sulla scheda. Nessun duplicato: se l'email e' gia' di un'altra scheda
    l'esito viene registrato ma l'email non viene copiata."""
    row = archive_rows[idx]
    row["_site_checked_at"] = utc_now()
    row["_site_result"] = result
    if not email:
        return False
    known = {norm_email(r.get("email")) for j, r in enumerate(archive_rows) if j != idx}
    if email in known:
        row["_site_result"] = "email gia' presente su altra scheda"
        return False
    row["email"] = email
    row["_updated_at"] = utc_now()
    row["email_src"] = page
    row["notes"] = ((row.get("notes") or "").rstrip() +
                    f" Email ricavata dal sito ufficiale ({page}): verificare prima del contatto.").strip()
    return True


def run(max_sites, max_seconds, dry_run=False, log=print):
    rows = load_json(ARCHIVE_PATH, [])
    now = datetime.datetime.now(datetime.timezone.utc)
    todo = [i for i, r in enumerate(rows) if needs_check(r, now)]
    # mai controllate prima, poi le piu' vecchie
    todo.sort(key=lambda i: rows[i].get("_site_checked_at") or "")
    log(f"Schede con sito e senza email: {len(todo)} da controllare "
        f"(budget {max_sites} siti / {max_seconds}s, archivio {len(rows)} schede)")
    todo = todo[:max_sites]
    if dry_run:
        for i in todo:
            log(f"  {rows[i].get('n')} -> {rows[i].get('site')}")
        return 0

    t0 = time.time()
    found = checked = 0
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS)
    try:
        pending = {}
        it = iter(todo)

        def submit_next():
            i = next(it, None)
            if i is not None and time.time() - t0 < max_seconds:
                pending[pool.submit(check_site, rows[i]["site"])] = i
                return True
            return False

        for _ in range(WORKERS):
            submit_next()
        while pending:
            done, _ = concurrent.futures.wait(
                pending, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                i = pending.pop(fut)
                try:
                    email, page, result = fut.result()
                except Exception as exc:  # un sito anomalo non deve fermare il giro
                    email, page, result = None, None, f"errore: {str(exc)[:80]}"
                checked += 1
                if apply_result(rows, i, email, page, result):
                    found += 1
                    log(f"  + {rows[i]['n']} ({rows[i].get('city') or '-'}): {email}")
                submit_next()
            if time.time() - t0 >= max_seconds and not done:
                break  # tempo scaduto: i thread in volo finiscono da soli (daemon)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        save_json(ARCHIVE_PATH, rows)
    log(f"\n=== ARRICCHIMENTO SITI === controllati: {checked} | email trovate: {found} | "
        f"durata: {int(time.time() - t0)}s")
    remaining = sum(1 for r in rows if needs_check(r, now))
    log(f"siti ancora da controllare: {remaining}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-sites", type=int, default=MAX_SITES)
    ap.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--site", help="prova un solo sito, senza toccare l'archivio")
    args = ap.parse_args()
    if args.site:
        email, page, result = check_site(args.site)
        print(json.dumps({"email": email, "pagina": page, "esito": result},
                         ensure_ascii=False, indent=2))
        return 0
    return run(args.max_sites, args.max_seconds, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
