# Coda di lavoro H24 — `cities.json`

La coda contiene **388 comuni italiani** e determina l'ordine con cui la ricerca
automatica H24 (`.github/workflows/petnote-prospecting-h24.yml`) processa il paese.

## Metodo di generazione (riproducibile)

1. Fonte: dataset pubblico **comuni-json** (matteocontrini/comuni-json),
   basato sull'archivio **ISTAT** ([CC BY 3.0 IT](https://creativecommons.org/licenses/by/3.0/it/)).
2. Regola: coda = i **388 comuni più popolosi d'Italia**, ordinati per
   popolazione decrescente (pari merito → codice ISTAT crescente).
   _Cutoff attuale: Fossano (CN), 24.710 abitanti._
3. Comando di rigenerazione:

   ```bash
   git clone --depth 1 https://github.com/matteocontrini/comuni-json.git /tmp/comuni-json
   python3 prospecting/tools/generate_queue.py --source /tmp/comuni-json/comuni.json
   ```

## Campi per comune

| Campo | Significato |
|---|---|
| `name` | Nome del comune (ISTAT) |
| `code` | Codice ISTAT (usato da Overpass per identificare il confine amministrativo, tag `ref:ISTAT`) |
| `sigla`, `province`, `region` | Anagrafica amministrativa |
| `population` | Popolazione (per il raggio di ricerca di fallback) |
| `lat`, `lon` | **null** all'inizio; vengono risolti alla prima ricerca Overpass e persistiti come cache |

## Note

- Il sistema interroga **solo OpenStreetMap** (Overpass API, licenza **ODbL**):
  nessuno scraping di directory con termini d'uso restrittivi.
- Il numero di comuni in coda è parametrizzato nello script
  (`--size`, default 388) e la velocità di avanzamento in
  `prospecting/config.json` (`cities_per_run`, default 6).
