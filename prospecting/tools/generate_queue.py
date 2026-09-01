#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera la coda di lavoro H24: prospecting/queue/cities.json

Metodo (deterministico e documentato):
  1. Fonte: dataset pubblico "comuni-json" (matteocontrini/comuni-json),
     archivio ISTAT (CC BY 3.0 IT), https://github.com/matteocontrini/comuni-json
     - colonne usate: nome, codice, sigla, provincia.nome, regione.nome, popolazione
     - NON vengono usati i CAP (parte senza licenza chiara del dataset).
  2. Regola: coda = i 388 comuni piu' popolosi d'Italia, ordinati per
     popolazione decrescente (pari merito -> codice ISTAT crescente).
  3. Output: array JSON di celle con lat/lon = null (risolti da
     prospecting/find_candidates.py via OpenStreetMap e poi aggiornati).

Uso:
  python3 prospecting/tools/generate_queue.py --source /percorso/comuni.json
  (senza --source usa una copia del dataset in /tmp/comuni-json/comuni.json)
"""

import argparse
import json
import os
import sys

QUEUE_SIZE = 388


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="/tmp/comuni-json/comuni.json",
                    help="percorso di comuni.json (dataset comuni-json)")
    ap.add_argument("--size", type=int, default=QUEUE_SIZE,
                    help="numero di comuni in coda (default 388)")
    ap.add_argument("--out", default=None,
                    help="file di destinazione (default prospecting/queue/cities.json)")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        print(f"ERRORE: dataset non trovato: {args.source}\n"
              "Scaricalo con: git clone https://github.com/matteocontrini/comuni-json.git /tmp/comuni-json",
              file=sys.stderr)
        return 1

    with open(args.source, encoding="utf-8") as fh:
        comuni = json.load(fh)

    if not isinstance(comuni, list) or not comuni:
        print("ERRORE: file dataset non valido", file=sys.stderr)
        return 1

    for c in comuni:
        for k in ("nome", "codice", "sigla", "popolazione"):
            if k not in c:
                print(f"ERRORE: campo mancante '{k}' nel dataset", file=sys.stderr)
                return 1

    comuni.sort(key=lambda c: (-c["popolazione"], c["codice"]))
    queue = comuni[: args.size]

    out = []
    for c in queue:
        out.append({
            "name": c["nome"],
            "code": c["codice"],
            "sigla": c.get("sigla"),
            "province": c.get("provincia", {}).get("nome"),
            "region": c.get("regione", {}).get("nome"),
            "population": c["popolazione"],
            "lat": None,
            "lon": None,
        })

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "queue", "cities.json")
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"Coda generata: {len(out)} comuni -> {out_path}")
    print(f"Ultimo in coda: {out[-1]['name']} (pop. {out[-1]['population']})")
    print("Nota: lat/lon sono null e vengono risolti in modo incrementale "
          "dalla pipeline H24 via OpenStreetMap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
