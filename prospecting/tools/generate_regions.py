#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera la coda REGIONALE H24 (ciclo 3+): copertura di TUTTI i comuni italiani.

Output:
  prospecting/queue/regions.json       20 regioni (ordine: popolazione decrescente)
  prospecting/queue/comuni_index.json  indice comune -> sigla provincia, per regione

Perche' una coda regionale: la coda per citta' (cities.json) copre solo i 388
comuni piu' popolosi (~meta' della popolazione). Con la restrizione email le
query Overpass restituiscono pochi elementi, quindi una sola query sul confine
regionale e' leggera e copre anche i ~7.500 comuni minori. L'indice dei comuni
serve ad attribuire citta'/provincia alle schede partendo da addr:city (OSM),
senza ulteriori query.

Metodo (deterministico):
  1. Fonte: dataset pubblico "comuni-json" (matteocontrini/comuni-json),
     archivio ISTAT (CC BY 3.0 IT). Colonne: nome, sigla, regione, popolazione.
  2. Confine regionale in OSM identificato dal codice ISO 3166-2 (tag
     "ISO3166-2", es. IT-25 = Lombardia), con fallback sul nome.

Uso:
  git clone --depth 1 https://github.com/matteocontrini/comuni-json.git /tmp/comuni-json
  python3 prospecting/tools/generate_regions.py --source /tmp/comuni-json/comuni.json
"""

import argparse
import json
import os
import sys
import unicodedata

# Codice regione ISTAT -> codice ISO 3166-2:IT (standard, stabile).
ISTAT_TO_ISO = {
    "01": "IT-21", "02": "IT-23", "03": "IT-25", "04": "IT-32", "05": "IT-34",
    "06": "IT-36", "07": "IT-42", "08": "IT-45", "09": "IT-52", "10": "IT-55",
    "11": "IT-57", "12": "IT-62", "13": "IT-65", "14": "IT-67", "15": "IT-72",
    "16": "IT-75", "17": "IT-77", "18": "IT-78", "19": "IT-82", "20": "IT-88",
}


def comune_key(name):
    """Chiave di confronto robusta ad accenti, apostrofi e trattini (addr:city e' libero)."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", " ").replace("-", " ").replace("`", " ")
    return " ".join(s.split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="/tmp/comuni-json/comuni.json",
                    help="percorso di comuni.json (dataset comuni-json)")
    ap.add_argument("--out-dir", default=None,
                    help="cartella di destinazione (default prospecting/queue)")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        print(f"ERRORE: dataset non trovato: {args.source}", file=sys.stderr)
        return 1
    with open(args.source, encoding="utf-8") as fh:
        comuni = json.load(fh)
    if not isinstance(comuni, list) or not comuni:
        print("ERRORE: file dataset non valido", file=sys.stderr)
        return 1

    regions, index = {}, {}
    for c in comuni:
        reg = c.get("regione") or {}
        code, name = reg.get("codice"), reg.get("nome")
        if code not in ISTAT_TO_ISO or not name:
            print(f"ERRORE: regione non riconosciuta per {c.get('nome')}: {reg}", file=sys.stderr)
            return 1
        r = regions.setdefault(code, {"name": name, "code": code, "iso": ISTAT_TO_ISO[code],
                                      "comuni": 0, "population": 0})
        r["comuni"] += 1
        r["population"] += int(c.get("popolazione") or 0)
        # in caso di omonimia nella stessa regione (raro) si tiene il piu' popoloso
        key = comune_key(c["nome"])
        prev = index.setdefault(name, {}).get(key)
        if prev is None or (c.get("popolazione") or 0) > prev[2]:
            index[name][key] = [c["nome"], c.get("sigla"), c.get("popolazione") or 0]

    out_regions = sorted(regions.values(), key=lambda r: (-r["population"], r["code"]))
    out_index = {reg: {k: v[:2] for k, v in sorted(m.items())} for reg, m in sorted(index.items())}

    out_dir = os.path.abspath(args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "queue"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "regions.json"), "w", encoding="utf-8") as fh:
        json.dump(out_regions, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "comuni_index.json"), "w", encoding="utf-8") as fh:
        json.dump(out_index, fh, ensure_ascii=False, separators=(",", ":"))

    print(f"Regioni: {len(out_regions)} | comuni indicizzati: "
          f"{sum(len(m) for m in out_index.values())} -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
