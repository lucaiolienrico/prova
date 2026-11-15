# REPORT ANALISI — repo `prova` (PetNote Prospecting / H24 Engine)

Data: 2026-11-15 · Branch analizzato: `ccr-4ceb3174-fp4yjw` (5b64069) + `origin/main` (359bd34)

## Analisi Preliminare

Repo = pipeline lead-generation per settore pet. Fonte principale OpenStreetMap/Overpass, GitHub Actions cron 4×/giorno, commit bot su `main`. Contiene anche: DB manuale (189 schede), landing `index.html`, README che vende il sistema come prodotto (€497–1.997).
Verificato: file, git log, `origin/main`, `archive.json`, output, run_log, test (12/12 OK, solo `enrich_sites`).

---

## 1. Stato

| Metrica | Valore | Fonte |
|---|---|---|
| Schede note totali (manuali + archivio, dedup) | 1.449 | `riepilogo.txt` |
| Archivio H24 | 1.265 (317 con email, 334 con sito, 230 sito+email) | `archive.json` |
| Output consegnato (solo email) | **361** (45 manuali, 316 auto) | `petnote_prospects.json` |
| Priorità | A+ 7 · A 49 · B 178 · C 109 · D 18 | `riepilogo.txt` |
| Shortlist A/B | 234 | idem |
| Run H24 totali | 78 | `progress.json` |
| Commit bot su `main` dal 10/11 | 15 in 5 giorni | `git log` |
| Dimensione | 9 MB; `candidates/runs/` 7,2 MB (836 file tracciati, 144 cartelle) | du / git ls-files |

Distribuzione: Lombardia 102 (28%), Lazio 37, Trentino-AA 31, Piemonte 26. Calabria 3, Basilicata 1, Molise 3, VdA 2. Categoria: Veterinari 139, Pet shop 80, Rifugi 56; Dog sitter / educatori / fisioterapisti = 0 (nessun tag OSM).

## 2. Problemi — per gravità

### P1 — Critici

| # | Problema | Evidenza | Impatto |
|---|---|---|---|
| 1 | **Fonte OSM satura.** Il motore non trova più nulla | Nuove per passaggio: P1 = 154 · P2 = 1 · P3 = 0 · P4 (6/20 regioni) = 0. Run con "0 nuove" consecutivi: ~17 | Cron 4×/giorno brucia Actions e inquina git senza produrre dati |
| 2 | **Fonte 2 (email da siti) NON attiva in produzione** | Commit 5b64069 (`enrich_sites.py`, test, recipe estesa) è solo sul branch. `origin/main` non ha `enrich_sites.py`, né step nel workflow (grep vuoto), né `website_enrichment` in config. Branch 15 commit dietro `main`, divergente | Unica leva di crescita reale (≈100 schede con sito ma senza email, stima da 334−230) ferma |
| 3 | **Rischio GDPR/compliance** | 361 email nominative-aziendali (115 gmail, 24 libero, 9 virgilio… = ditte individuali) committate nel repo; Pages `lucaiolienrico.github.io/prova` suggerisce repo pubblico (**visibilità non verificata**). README dichiara "nessuno scraping directory" ma output contiene fonti PagineGialle (3), Facebook (3), Cani.com (2) | Esposizione dati personali + incoerenza con ToS dichiarati |

### P2 — Rilevanti

| # | Problema | Evidenza |
|---|---|---|
| 4 | **Docs/landing falsi o stantii** | README + `index.html`: "1.155 prospect, 55 run, 280+/388 comuni". Reale: 361 output / 1.449 noti, 78 run, 388/388 + ciclo regionale. `RIAVVIO.md` cita `H24_patches/` come "da copiare" ma workflow già in `.github/workflows/`; `H24_patches/` è duplicato identico |
| 5 | **Qualità dati** | 4 email malformate multi-indirizzo (`a@x;b@x`, `x@y;`); 68 senza città, 76 senza provincia (addr:city mancante OSM, ~30% elementi per regione "senza comune"); regione duplicata "Trentino-Alto Adige" (1) vs "…/Südtirol" (30); 2 senza regione |
| 6 | **Bias di copertura OSM** | Sud e piccole regioni quasi vuote; non è lacuna del codice ma di mappatura OSM. Score non lo compensa |
| 7 | **Pitch commerciale vs contenuto** | README vende "H24 Prospecting Engine" (licenza commerciale, prezzi) mentre il repo contiene dati reali di un cliente/progetto (PetNote) → mix prodotto/dati |

### P3 — Minori

| # | Problema |
|---|---|
| 8 | `run_log.md` 87 KB e crescente; `runs/<giro>/<regione>.json` (fino a 3.962 righe/file) mai riletti dalla pipeline → bloat git senza valore |
| 9 | Test solo per `enrich_sites` (e solo su branch). Nessun test per `process.py`, dedup, `find_candidates.py` (solo fixture offline manuale) |
| 10 | `config.json` con chiavi di commento inline e riga `weights` con spazi anomali (leggibile ma fragile) |
| 11 | Merge-risk: sul branch `config.json` ha recipe ampliata (pet_supplies, animal_training); `main` l'ha ridotta → conflitto certo al merge |

## 3. Cosa funziona

- Anti-duplicato a 5 controlli: 0 duplicati email nell'output (361 uniche).
- Tracciabilità: `source`/`source_url`/`osm_id` per scheda; "mai inventare dati" rispettato (null se assente).
- Resilienza run: `continue-on-error`, `concurrency`, endpoint Overpass di fallback, auto-restart a 7 giorni.
- Test di `enrich_sites` 12/12 OK; estrazione con robots.txt e User-Agent dichiarato.

## 4. Raccomandazioni (priorità)

| Prio | Azione | Beneficio |
|---|---|---|
| 1 | Rebase/merge branch su `main`, risolvere conflitto `config.json`, aggiungere step `enrich_sites.py` al workflow `main` | Attiva unica fonte crescente |
| 2 | Cron: 4×/giorno → 1×/settimana (o stop se 0 nuove per N giri); commit solo se cambiano output | Meno rumore/costi |
| 3 | Decidere visibilità repo; se pubblico → togliere `output/*.csv/json` e `archive.json` dal tracking (artifact privato) | GDPR |
| 4 | Rimuovere/etichettare righe PagineGialle/Facebook o allineare README | Coerenza ToS |
| 5 | Normalizzare email multiple (split sul `;`), fondere regione Trentino, ripulire sede da `addr:city` mancante con reverse geocoding da lat/lon (dati già in archivio) | +qualità, −68 senza città |
| 6 | Aggiornare README/`index.html`/`RIAVVIO.md`; eliminare `H24_patches/` | Credibilità |
| 7 | Ignorare `candidates/runs/` o ruotare/comprimere; troncare `run_log.md` | −7 MB, repo leggero |
| 8 | Test per `process.py` (scoring, dedup, require_email) | Regressioni |
| 9 | Nuove fonti lecite per categorie a 0 (educatori, dog sitter): registri pubblici ENCI/ordini veterinari/Comuni (open data) | Copertura |

## 5. Limiti dell'analisi

- Visibilità repo e stato reale Actions (permessi, minuti) **non verificati**.
- Stima "≈100 schede con sito senza email" ricavata da 334−230 sull'archivio **del branch**; in `main` può differire.
- Non ho eseguito query Overpass né contattato i siti (rete/regole del progetto).
