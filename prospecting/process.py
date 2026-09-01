#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PetNote Prospecting Pipeline
- Carica i file grezzi prospecting/raw/*.json (estratti a mano da fonti pubbliche)
- Normalizza citta'/provincia/telefoni/email/social
- Deduplica (email, sito, telefono+similarita' nome, nome+citta')
- Calcola data_quality, score commerciale e priorita'
- Emette output/petnote_prospects.json e output/petnote_prospects.csv
"""
import json, re, csv, glob, os, difflib

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = sorted(glob.glob(os.path.join(BASE, "raw", "*.json")))
OUT_DIR = os.path.join(BASE, "output")
os.makedirs(OUT_DIR, exist_ok=True)

# ---------- CONFIG (tutto modificabile da prospecting/config.json) ----------
CFG_PATH = os.path.join(BASE, "config.json")
CFG = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else {}

CANONICAL_CATEGORIES = CFG.get("categories", [
    "Veterinari", "Cliniche veterinarie", "Ambulatori veterinari", "Ospedali veterinari",
    "Canili", "Rifugi per animali", "Associazioni animaliste", "Allevatori",
    "Allevamenti professionali", "Educatori cinofili", "Addestratori", "Centri cinofili",
    "Scuole per cani", "Pet shop", "Negozi per animali", "Toelettature",
    "Pensioni per animali", "Pet hotel", "Dog sitter", "Cat sitter",
    "Professionisti del comportamento animale", "Fisioterapisti veterinari",
    "Servizi di pet care", "Agenzie e servizi dedicati agli animali domestici",
])

BASE_SCORE = dict(CFG.get("base_score", {}))
SCORE_DEFAULT = BASE_SCORE.pop("_default", 20)

W = dict({
    "website": 14, "email": 14, "phone": 12, "instagram_url": 8, "facebook_url": 7,
    "address": 8, "contact_name": 6, "subcategory": 3, "digital_channel": 4,
    "rating_reviews": 6, "social_reach": 6, "updated_recent": 3,
    "chain_group_penalty": -12, "unverified_penalty_each": 3, "unverified_penalty_cap": 2,
    "old_source_penalty": 3,
})
W.update(CFG.get("weights", {}))

PRIO = CFG.get("priority_thresholds", {"A+": 90, "A": 80, "B": 65, "C": 50})
S_MIN, S_MAX = CFG.get("score_min", 5), CFG.get("score_max", 100)
OUT_F = CFG.get("output", {})
F_JSON = OUT_F.get("json", "petnote_prospects.json")
F_CSV = OUT_F.get("csv", "petnote_prospects.csv")
F_SHORT = OUT_F.get("shortlist", "shortlist_AB.csv")
F_SUM = OUT_F.get("riepilogo", "riepilogo.txt")

STOPWORDS = {"d'", "de", "del", "della", "delle", "di", "da", "dei", "e", "a", "in", "al"}
CITY_FIX = {
    "San Pancrazio (Russi)": ("Russi", "Frazione San Pancrazio"),
    "Ricadi (Santa Domenica)": ("Ricadi", "Localita' Santa Domenica di Ricadi"),
    "Canalicchio (Tremestieri Etneo)": ("Tremestieri Etneo", "Frazione Canalicchio, Piazza Tivoli"),
    "Tivoli / Roma est (da confermare)": ("Tivoli", "Prefisso 06 tra i contatti: possibile sede Roma est"),
    "Ricadi (zona Tropea-Ricadi)": ("Ricadi", "Zona Costa degli Dei tra Tropea e Ricadi"),
    "Bassano del Grappa (zona Rosà)": ("Bassano del Grappa", "Insegna 'Rosàflor': possibile sede a Rosà (VI)"),
    "Roma (zona, da confermare)": ("Roma", "Zona esatta da confermare"),
    "Brunico (zona, da confermare)": ("Brunico", "Zona da confermare (prefisso 0474 Val Pusteria)"),
    "Roma / zona Tivoli (da confermare)": ("Roma", "Attiva anche nella zona tiburtina; sede da confermare"),
    "Vico Equense (da confermare)": ("Vico Equense", "Geocoordinate directory in penisola sorrentina: da confermare"),
    "Campobasso (provincia, comune da confermare)": ("Campobasso", "Comune esatto da confermare (provincia CB)"),
    "Campobasso (da confermare)": ("Campobasso", "Comune desunto dal contesto di ricerca: da confermare"),
    "Gorizia (da confermare)": ("Gorizia", "Comune desunto dal prefisso 0481: da confermare"),
    "Isola di Capo Rizzuto": ("Isola di Capo Rizzuto", None),
    "Nuoro (zona, da confermare)": ("Nuoro", None),
}

def smart_title(s):
    if not s: return None
    ws = s.strip()
    def cap_word(w, first=False):
        lw = w.lower()
        if lw in STOPWORDS and not first:
            return lw
        if "'" in w:
            parts = w.split("'")
            firstpart = parts[0][0].upper() + parts[0][1:].lower()
            if not first and (lw.startswith("d'") or lw.startswith("l'") or lw.startswith("dell'")):
                firstpart = parts[0].lower()
            rest = [p[0].upper() + p[1:].lower() for p in parts[1:]]
            return "'".join([firstpart] + rest)
        return w[0].upper() + w[1:].lower()
    tokens = ws.split()
    return " ".join(cap_word(t, i == 0) for i, t in enumerate(tokens))

def norm_phone(tel):
    if not tel: return None
    parts = [p.strip() for p in re.split(r"[,;/]", tel) if p.strip()]
    out = []
    for p in parts:
        d = re.sub(r"\D", "", p)
        if not d: continue
        if d.startswith("0039"): d = d[4:]
        elif d.startswith("39") and len(d) >= 11: d = d[2:]
        if d[0] in "03" and 8 <= len(d) <= 10:
            out.append("+39 " + d)
        else:
            out.append(d + " (formato da verificare)")
    # dedup preservando ordine
    seen, res = set(), []
    for p in out:
        k = re.sub(r"\D", "", p)
        if k not in seen:
            seen.add(k); res.append(p)
    return ", ".join(res) if res else None

def norm_site(site, notes_extra):
    if not site: return None
    s = site.strip()
    if "(" in s or " " in s or s.startswith("www.struttureveterin"):
        notes_extra.append("Sito grezzo non utilizzabile: " + s)
        return None
    if not s.lower().startswith("http"):
        s = "https://" + s
    return s

def site_key(site):
    if not site: return None
    s = re.sub(r"^https?://", "", site.lower())
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/").split("/")[0]

def norm_email(e):
    if not e: return None
    return e.strip().lower() if "@" in e and "PEC:" not in e else None

def name_tokens(n):
    n = re.sub(r"[^a-zàèéìòù'0-9 ]", " ", n.lower())
    drop = {"di","del","della","delle","dei","da","d","il","la","lo","i","le","gli","e","s","a","snc","srl","sas","ssd","arl","asd","odv","onlus","ambulatorio","veterinario","veterinaria","centro","rifugio","pet","dog","zampa","cani","gatti","dr","dott","dottssa","ssa","ss"}
    return set(t for t in n.split() if t not in drop and len(t) > 1)

def similar_names(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb: return False
    inter = len(ta & tb)
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    # soglia prudente: almeno 2 token distintivi in comune OPPURE nomi molto simili
    return inter >= 2 or ratio > 0.72

# ---------- LOAD ----------
# 1) ondate manuali (raw/wave*.json) ...
rows = []
for f in RAW:
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
    for r in data:
        r["_wave"] = os.path.basename(f)
        rows.append(r)

# 2) ... + archivio della ricerca AUTOMATICA H24 (OpenStreetMap),
#    mantenuto da prospecting/find_candidates.py (anti-duplicato sui 5 controlli).
ARCHIVE = os.path.join(BASE, "candidates", "archive.json")
if os.path.exists(ARCHIVE):
    with open(ARCHIVE, encoding="utf-8") as fh:
        data = json.load(fh)
    for r in data:
        r["_system"] = "automatica"
        rows.append(r)
    print(f"  + archivio automatico (H24): {len(data)} righe")

print(f"Righe grezze caricate: {len(rows)}")

unknown_cats = sorted({r["cat"] for r in rows} - set(CANONICAL_CATEGORIES))
if unknown_cats:
    print("ATTENZIONE categorie non canoniche:", unknown_cats)

# ---------- NORMALIZE + DEDUP ----------
finals = []
index_email, index_site, index_phone, index_namecity = {}, {}, {}, {}

def try_merge(r):
    """restituisce l'indice del duplicato oppure None"""
    e = norm_email(r.get("email"))
    if e and e in index_email: return index_email[e]
    sk = site_key(norm_site(r.get("site"), []))
    if sk and sk in index_site: return index_site[sk]
    tels = [re.sub(r"\D", "", t) for t in (r.get("tel") or "").split(",") if t.strip()]
    for t in tels:
        if t in index_phone and similar_names(r["n"], finals[index_phone[t]]["business_name"] if "business_name" in finals[index_phone[t]] else finals[index_phone[t]]["n"]):
            return index_phone[t]
    nc = (re.sub(r"\s+", " ", r["n"].lower().strip()), (r.get("city") or "").lower())
    if nc[1] and nc in index_namecity: return index_namecity[nc]
    return None

def merge_into(base, new):
    for k, v in new.items():
        if k.startswith("_"): continue
        if (base.get(k) in (None, "", [])) and v not in (None, "", []):
            base[k] = v
        elif k == "notes" and v and v != base.get("notes"):
            base["notes"] = (base.get("notes") or "") + " ⧉ " + v

merged_count = 0
for r in rows:
    dup = try_merge(r)
    if dup is not None:
        merge_into(finals[dup], r)
        merged_count += 1
        continue
    idx = len(finals)
    finals.append(r)
    e = norm_email(r.get("email"))
    if e: index_email[e] = idx
    sk = site_key(norm_site(r.get("site"), []))
    if sk: index_site[sk] = idx
    for t in (r.get("tel") or "").split(","):
        d = re.sub(r"\D", "", t)
        if d: index_phone[d] = idx
    nc = (re.sub(r"\s+", " ", r["n"].lower().strip()), (r.get("city") or "").lower())
    if nc[1]: index_namecity[nc] = idx

print(f"Duplicati fusi: {merged_count}  ->  schede finali: {len(finals)}")

# ---------- BUILD OUTPUT ----------
def build(r):
    extra_notes = []
    city = r.get("city")
    prov = (r.get("prov") or "")
    if prov:
        m = re.match(r"^([A-Za-z]{1,2})", prov.strip())
        prov_clean = m.group(1).upper() if m else prov.strip().upper()[:3]
        if "(" in prov or "confermare" in prov:
            extra_notes.append("Provincia da confermare: " + prov)
    else:
        prov_clean = None
    if city and city in CITY_FIX:
        fixed, note = CITY_FIX[city]
        if note: extra_notes.append(note)
        city = fixed
    elif city and "(" in city:
        main, note = city.split("(", 1)
        city = main.strip()
        extra_notes.append("Nota sede: " + note.rstrip(")"))
    city = smart_title(city) if city else None

    site = norm_site(r.get("site"), extra_notes)
    email = norm_email(r.get("email"))
    pec = None
    if r.get("email") and "PEC:" in (r.get("other") or ""):
        pec = r["other"].replace("PEC:", "").strip()
    tel = norm_phone(r.get("tel"))
    ig_raw = r.get("ig")
    ig_user, ig_url = None, None
    if ig_raw:
        if " " in ig_raw.strip():
            extra_notes.append("Instagram: " + ig_raw.strip())
        else:
            ig_user = ig_raw.strip().lstrip("@")
            ig_url = f"https://www.instagram.com/{ig_user}/"
    fb = r.get("fb")
    if fb and not fb.startswith("http"):
        extra_notes.append("Facebook: " + fb.strip())
        fb = None
    other = r.get("other") or None
    notes = r.get("notes") or ""
    if extra_notes:
        notes = (notes + " | " if notes else "") + "; ".join(extra_notes)

    out = {
        "business_name": r["n"].strip(),
        "category": r["cat"],
        "subcategory": r.get("sub"),
        "city": city,
        "province": prov_clean,
        "region": r.get("reg"),
        "address": (r.get("addr") or None),
        "website": site,
        "email": email,
        "phone": tel,
        "instagram_username": ig_user,
        "instagram_url": ig_url,
        "facebook_url": fb,
        "contact_name": r.get("contact"),
        "source": r.get("src"),
        "source_url": r.get("srcurl"),
        "provenienza": "automatica" if r.get("_system") == "automatica" else "manuale",
        "data_quality": 0,
        "score": 0,
        "priority": "",
        "notes": notes or None,
    }
    if r.get("_found_at"):
        out["found_at"] = r["_found_at"]
    if r.get("osm_id") is not None:
        out["osm_id"] = r["osm_id"]

    fields = ["business_name","category","subcategory","city","province","region","address","website","email","phone","instagram_url","facebook_url","contact_name"]
    out["data_quality"] = round(100 * sum(1 for f in fields if out[f]) / len(fields))

    sc = BASE_SCORE.get(out["category"], SCORE_DEFAULT)
    if out["website"]: sc += W["website"]
    if out["email"]: sc += W["email"]
    if out["phone"]: sc += W["phone"]
    if out["instagram_url"]: sc += W["instagram_url"]
    if out["facebook_url"]: sc += W["facebook_url"]
    if out["address"]: sc += W["address"]
    if out["contact_name"]: sc += W["contact_name"]
    if out["subcategory"]: sc += W["subcategory"]
    blob = " ".join(str(out.get(k) or "") for k in ("subcategory","notes")).lower()
    raw_other = (r.get("other") or "").lower(); raw_desc = (r.get("desc") or "").lower()
    everything = blob + " " + raw_other + " " + raw_desc
    if re.search(r"whatsapp|online|consegn|ordina e ritira|prenotaz", everything):
        sc += W["digital_channel"]
    if re.search(r"4,\d|4\.\d|5,0|5\.0", everything) and re.search(r"recension|rating", everything):
        sc += W["rating_reviews"]
    if re.search(r"\d{3,}[^.]{0,30}(like|follower|recension)|[0-9]{1,2}\.[0-9]{3} (like|recensioni|follower)|16\.000", everything):
        sc += W["social_reach"]
    if re.search(r"20(24|25|26)", everything):
        sc += W["updated_recent"]
    if "catena" in everything or "insegna" in everything or "corporate" in everything:
        sc += W["chain_group_penalty"]
    pen = everything.count("da verificare") + everything.count("da confermare") + everything.count("da integrare")
    sc -= min(pen, W["unverified_penalty_cap"]) * W["unverified_penalty_each"]
    if "fonte del 2016" in everything or "fonte del 2018" in everything:
        sc -= W["old_source_penalty"]
    out["score"] = max(S_MIN, min(S_MAX, sc))
    s = out["score"]
    out["priority"] = "A+" if s >= PRIO["A+"] else "A" if s >= PRIO["A"] else "B" if s >= PRIO["B"] else "C" if s >= PRIO["C"] else "D"
    return out

results = [build(r) for r in finals]
results.sort(key=lambda x: ((x["category"] or ""), (x["region"] or "~~~"), (x["province"] or "~~"), (x["city"] or "~~~"), -x["score"]))

with open(os.path.join(OUT_DIR, F_JSON), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

ALL_FIELDS = []
for _r in results:
    for _k in _r:
        if _k not in ALL_FIELDS:
            ALL_FIELDS.append(_k)

with open(os.path.join(OUT_DIR, F_CSV), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=ALL_FIELDS, delimiter=";")
    w.writeheader()
    for r in results:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})

# ---------- SHORTLIST OPERATIVA (A+/A/B, pronta per l'azione commerciale) ----------
short = sorted([r for r in results if r["priority"] in ("A+", "A", "B")], key=lambda x: -x["score"])
with open(os.path.join(OUT_DIR, F_SHORT), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=ALL_FIELDS, delimiter=";")
    w.writeheader()
    for r in short:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
print(f"Shortlist operativa ({F_SHORT}): {len(short)} prospect (A+/A/B)")

# ---------- STATS ----------
from collections import Counter
n = len(results)
by_prio = Counter(r["priority"] for r in results)
by_cat = Counter(r["category"] for r in results)
by_reg = Counter(r["region"] for r in results)
cities = sorted({(r["region"], r["province"], r["city"]) for r in results if r["city"]})
with_contact = sum(1 for r in results if r["email"] or r["phone"])
with_site = sum(1 for r in results if r["website"])
n_auto = sum(1 for r in results if r.get("provenienza") == "automatica")
n_man = n - n_auto

print(f"\n=== RIEPILOGO ===")
print(f"Prospect totali: {n} (manuali: {n_man}, automatici H24: {n_auto})")
print(f"Con contatto diretto (email/tel): {with_contact}  ({100*with_contact//n}%)")
print(f"Con sito web: {with_site}")
print("Priorita':", dict(by_prio))
print("Regioni coperte:", len([k for k in by_reg if k]), dict(sorted(by_reg.items(), key=lambda x: -x[1])))
print(f"Comuni/localita' distinti: {len(cities)}")
print("Per categoria:", dict(sorted(by_cat.items(), key=lambda x: -x[1])))

# ---------- RIEPILOGO TESTUALE (output/riepilogo.txt) ----------
import datetime
lines = []
lines.append("PETNOTE PROSPECTING - RIEPILOGO AUTOMATICO")
lines.append("Generato: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
lines.append("=" * 60)
lines.append(f"Prospect totali: .............. {n} (manuali {n_man}, H24 {n_auto})")
lines.append(f"Con contatto diretto ......... {with_contact} ({100*with_contact//n}%)")
lines.append(f"Con sito web ................. {with_site}")
lines.append(f"Shortlist A+/A/B ............. {len(short)}")
lines.append(f"Comuni/localita' distinti .... {len(cities)}")
lines.append("")
lines.append("PRIORITA': " + ", ".join(f"{k}={by_prio.get(k,0)}" for k in ("A+","A","B","C","D")))
lines.append("")
lines.append("PER REGIONE:")
for k, v in sorted(by_reg.items(), key=lambda x: -x[1]):
    reg_name = k or "(senza regione)"
    lines.append(f"  {reg_name:<22} {v}")
lines.append("")
lines.append("PER CATEGORIA:")
for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
    lines.append(f"  {k:<46} {v}")
lines.append("")
lines.append("TOP 15 PROSPECT PER SCORE:")
for r in sorted(results, key=lambda x: -x["score"])[:15]:
    lines.append(f"  {r['score']:>3} {r['priority']:<2}  {r['business_name'][:52]:<52} {r['city'] or '-':<20} {r['category']}")
with open(os.path.join(OUT_DIR, F_SUM), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"Riepilogo scritto in {F_SUM}")
