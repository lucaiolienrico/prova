# RIAVVIO LAVORO — stato e istruzioni operative (aggiornato)

> Nota sulla versione precedente di questo file: il commit locale `0bed4a8` e la
> cartella `H24_patches/` citati nella versione precedente **non esistono più**
> (erano solo nel sandbox della sessione chiusa e non sono mai arrivati su GitHub).
> Il sistema H24 è stato **ricostruito da zero e testato** — vedi §1.

## 1. Stato attuale

Tutto è in questo repository, sul branch `main` (attraverso la PR di sessione):

- **Database manuale**: `prospecting/raw/wave*.json` → 189 prospect, **mai modificati**
  i dati dei prospect esistenti.
- **Sistema H24 (nuovo, ricostruito)**:
  - `H24_patches/petnote-prospecting-h24.yml` — workflow pronto: cron 6h
    (00/06/12/18 UTC) + avvio manuale con parametro `batch`. **Deve essere copiato
    in `.github/workflows/` per essere attivo** (v. §5: il client di questa sessione
    non ha il permesso `workflows` di GitHub per creare quel file da solo);
  - `prospecting/find_candidates.py` — motore di ricerca (OpenStreetMap/Overpass, ODbL),
    anti-duplicato su 5 controlli, archivio unico, run log;
  - `prospecting/queue/cities.json` — coda di **388 comuni** (ISTAT, in ordine di
    popolazione), rigenerabile con `prospecting/tools/generate_queue.py`;
  - `prospecting/process.py` — pipeline aggiornata: carica l'archivio automatico,
    aggiunge `provenienza` (manuale/automatica) agli output;
  - `prospecting/tests/fixture_h24.json` — test offline riproducibile della ricerca.

## 2. Come funziona il sistema H24

1. **Niente server, niente PC acceso**: gira su GitHub Actions.
2. Ogni 6 ore (00:00, 06:00, 12:00, 18:00 UTC) il workflow:
   1. prende le prossime `cities_per_run` (default **6**) città dalla coda;
   2. interroga Overpass (OpenStreetMap, licenza ODbL) sui confini del comune,
      con fallback a raggio per i confini non mappati;
   3. converte gli elementi OSM in schede (vet, pet shop, toelettature, pensioni,
      canili/rifugi, allevamenti);
   4. passa ogni candidato ai **5 controlli anti-duplicato** (id oggetto OSM,
      email, telefono, sito, nome+città anche simile) contro **tutto** l'archivio
      (manuale + automatico); se esiste già, integra solo i contatti mancanti;
   5. salva risultati e **committa e pusha** automaticamente su main.
3. **Avvio manuale**: Actions → "PetNote Prospecting H24" → **Run workflow** →
   scegli il numero di città (`batch`, default 6).
4. **Dove vedi i risultati**:
   - `prospecting/output/petnote_prospects.json|csv` (database completo, rigenerato);
   - `prospecting/candidates/archive.json` (archivio schede automatiche) e
     `prospecting/candidates/runs/` (dati grezzi per città e giro);
   - diario in `prospecting/state/run_log.md`, stato coda in
     `prospecting/state/progress.json`.

## 3. Comandi utili (dalla root del repo)

```bash
python3 prospecting/find_candidates.py --list-done     # stato coda (x completate/388)
python3 prospecting/find_candidates.py --batch 6       # giro manuale (default 6)
python3 prospecting/find_candidates.py --cities "Roma,Milano"   # giro su città specifiche
python3 prospecting/process.py                          # rigenera output/scoring
python3 prospecting/find_candidates.py --offline-fixture prospecting/tests/fixture_h24.json \
    --cities "Roma,Milano"                              # TEST offline (nessuna rete)
python3 prospecting/find_candidates.py --reset-progress # nuovo ciclo (riparte dalla cima)
```

## 4. Regole di rispetto (invariate)

- **Niente messaggi automatici** agli esercenti: la fase di contatto è sempre manuale.
- **Solo OpenStreetMap** (ODbL): nessuno scraping di directory con termini d'uso restrittivi.
- Nessun dato inventato: i contatti sono copiati dalla fonte dichiarata
  (`source`/`source_url` in ogni scheda), e le schede OSM riportano un promemoria
  di verifica prima del contatto.
- Le categorie senza un tag OSM standard (dog sitter, educatori cinofili, ecc.)
  **non** vengono ricercate automaticamente: restano un'attività manuale.

## 5. Prima attivazione (dopo il merge) — 1 minuto, per un motivo di permessi

Il client GitHub di questa sessione (App `arena-ai-coding-agent`) **non ha il
permesso `workflows`**, quindi non può creare file dentro `.github/workflows/`.
Il workflow completo è in `H24_patches/petnote-prospecting-h24.yml` e va copiato
una sola volta:

1. Su GitHub: repository `Prova` → **Add file → Create new file** → percorso
   `.github/workflows/petnote-prospecting-h24.yml` → incolla il contenuto di
   `H24_patches/petnote-prospecting-h24.yml` → **Commit changes** (ramo `main`).
2. Scheda **Actions** → se chiede, "I understand, enable them".
3. Da quel momento il cron parte da solo (00/06/12/18 UTC). Per il primo giro
   immediato: **Actions → PetNote Prospecting H24 → Run workflow** (batch default 6).

> In alternativa: riconnetti GitHub da Arena con un'App che abbia il permesso
> `Workflows: read and write`; se la nuova connessione lo consente, l'agente può
> completare il passaggio 1 automaticamente.

## 6. Nota: `petnote_landing_page.html`

Il vecchio branch di sessione contiene anche `petnote_landing_page.html` (landing
page statica, 1398 righe) **non inclusa** in questa PR, perché estranea al sistema
H24. Se serve nel repository, si può aggiungere in una PR dedicata.
