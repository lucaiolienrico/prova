# PetNote — Database Nazionale Prospect (settore pet)

Database progressivo di potenziali partner commerciali PetNote, organizzato per
**categoria → regione → provincia → città → attività → contatti → qualità → score → priorità**.

Sessione corrente: prima tranche operativa (10 ondate di ricerca), focalizzata su città
**medio-piccole e comuni**, come da direttiva (niente concentrazione sulle sole grandi città).

---

## Struttura

```
prospecting/
├── README.md                    ← metodo, rubriche, compliance
├── registry.md                  ← registro ricerca continua (categoria × città completate)
├── REPORT_USO.md                ← GUIDA OPERATIVA: come usare il database
├── config.json                  ← parametri pipeline (categorie, pesi scoring, soglie, H24)
├── process.py                   ← pipeline: normalizza → deduplica → scoring → output
├── raw/                         ← estratti grezzi per ondata (fonte primaria dichiarata per ogni riga)
│   ├── wave01_altamura.json     ... wave10_roma_ospedali.json
├── queue/                       ← coda di lavoro H24 (388 comuni, dati ISTAT)
│   ├── cities.json              ← generata da prospecting/tools/generate_queue.py
│   └── README.md                ← metodo e attribuzione
├── find_candidates.py           ← ricerca automatica H24 (OpenStreetMap/Overpass, ODbL)
├── candidates/                  ← output del sistema H24
│   ├── archive.json             ← archivio unico schede automatiche (anti-duplicato)
│   └── runs/<giro>/<città>.json ← dati grezzi per città
├── state/                       ← run_log.md (diario), progress.json (coda)
├── tools/generate_queue.py      ← rigenera la coda comuni
└── tests/fixture_h24.json       ← test offline riproducibile della ricerca H24
```

Rigenera gli output dopo ogni nuova ondata o modifica di `config.json`:

```bash
python3 prospecting/process.py
```

Il sistema H24 (attivato dal workflow `.github/workflows/petnote-prospecting-h24.yml`,
ogni 6 ore o manualmente) trova nuove schede da **OpenStreetMap** e le aggiunge
all'archivio; `process.py` produce poi il database unificato con il campo
`provenienza` (`manuale` / `automatica`). I dati dei prospect manuali non vengono
mai modificati dal sistema automatico.

---

## Ricerca automatica H24 (OpenStreetMap)

- **Fonte**: solo OpenStreetMap via Overpass API (licenza **ODbL**). Nessuno scraping
  di directory con termini d'uso restrittivi.
- **Copertura**: coda di 388 comuni (i più popolosi d'Italia, dati ISTAT) processati
  a `cities_per_run` (default 6) città per giro; 4 giri/giorno via GitHub Actions.
- **Categorie automatiche**: Veterinari, Pet shop, Toelettature, Pensioni per animali,
  Canili, Rifugi per animali, Allevamenti professionali, Allevatori — mapping in
  `config.json → overpass.recipe`. Le altre categorie non hanno un tag OSM standard
  e restano ricerca manuale.
- **Anti-duplicato**: ogni candidato passa 5 controlli (id oggetto OSM, email,
  telefono, sito, nome+città anche simile) contro **tutto** l'archivio; se la scheda
  esiste già, vengono integrati **solo** i contatti mancanti (mai sovrascritture).
- **Tracciabilità**: ogni scheda automatica riporta `source` (Overpass API, ODbL),
  `source_url` (pagina elemento OSM), `osm_id`, `found_at`, `provenienza: automatica`
  e un promemoria di verifica dei contatti in `notes`.
- **Comandi di base**, dalla root del repo:
  ```bash
  python3 prospecting/find_candidates.py --batch 6      # giro di 6 città
  python3 prospecting/find_candidates.py --list-done    # stato coda
  python3 prospecting/process.py                        # rigenera gli output
  ```

## Metodo di raccolta (manuale)

1. Ricerche web separate per **combinazione `categoria × città`** (es. `veterinari Altamura`,
   `toelettatura cani Altamura`, `canile rifugio Altamura`…).
2. Più fonti per combinazione: directory di settore (PagineGialle/PagineBianche, Cani.com,
   PensionePerAnimali, ToelettaturaPro…), siti ufficiali, pagine social pubbliche, portali
   istituzionali (Comuni, reti civiche provinciali, CSV), riviste di settore (PetB2B).
3. Trascrizione manuale assistita in `raw/` con **conservazione della fonte e URL** per ogni scheda.
4. Espansione geografica per conurbazione: ricerche su capoluoghi medi che hanno coperto
   automaticamente i comuni della provincia (es. Aci Catena/Aci Sant'Antonio da Acireale;
   Guarene/Vezza d'Alba/Santa Vittoria d'Alba da Alba).

## Regole di integrità dei dati (rigorose)

- **Mai inventare** email, telefoni, nomi, social o indirizzi: se non pubblicamente presente → `null`.
- Ogni dato di contatto è copiato **letteralmente** dalla fonte pubblica indicata in `source`/`source_url`.
- Numeri troncati o sospetti dalle directory (es. `0546 32384`, `0481 82173`) sono marcati
  in `notes` come da riverificare.
- Verifiche anti-confusione documentate, ad esempio:
  - *Zoe World Tivoli* NON è a Tivoli: è in Piazza Tivoli a Canalicchio (Tremestieri Etneo, CT) → registrata in Sicilia.
  - *Ariosto S.r.l.* (toelettatura) ≠ *Rifugio Ariosto* (Acireale): due soggetti distinti tenuti separati.
  - *Pezzuto e Piano* ≠ *Pizzuto S.a.s.* (Campobasso): omonimi, sedi diverse → schede distinte.
  - *Gattile Nati Liberi* condivide il numero del *Rifugio Ramondetti-Cassardo* (TO): non fusi per cautela, nota incrociata in entrambe le schede.
  - Fusioni effettuate solo con alias confermati (stesso indirizzo/telefono): es. *Centro Medico/Centro Veterinario Sant'Anna* di Altamura; *Qua La Zampa* Vibo Valentia (due voci directory fuse).

## Modello dati (output)

Campi per prospect: `business_name, category, subcategory, city, province, region, address,
website, email, phone, instagram_username, instagram_url, facebook_url, contact_name, source,
source_url, provinenza (manuale/automatica), data_quality (0-100), score (0-100),
priority (A+/A/B/C/D), notes` (+ `found_at`, `osm_id` per le schede automatiche).

- `data_quality` = % di campi popolati su 13 campi chiave
  (nome, categoria, sottocategoria, città, provincia, regione, indirizzo, sito, email,
  telefono, Instagram, Facebook, referente).
- `category` usa sempre la nomenclatura canonica delle 24 categorie previste per PetNote.

## Rubrica punteggio commerciale (0-100)

| Componente | Punti |
|---|---|
| Base per categoria (fit con PetNote: ospedali/cliniche vet > centri cinofili/pensioni/pet shop > singoli professionisti; rifugi/associazioni base minore ma alto valore adozioni) | 18–32 |
| Sito web proprio | +14 |
| Email pubblica | +14 |
| Telefono pubblico | +12 |
| Instagram / Facebook pubblici | +8 / +7 |
| Indirizzo | +8 |
| Nome referente pubblico | +6 |
| Sottocategoria precisa | +3 |
| WhatsApp / prenotazioni o consulenze online / consegne | +4 |
| Rating ≥ 4 con recensioni verificabili | +6 |
| Social reach rilevante (migliaia di follower/like) | +6 |
| Fonte aggiornata 2024-2026 | +3 |
| Catena nazionale (partnership non locale) | −12 |
| Dati da verificare/confermare/integrare | −3 cad. (max −6) |
| Fonte datata (2016/2018) | −3 |

Classi: **90-100 = A+** · **80-89 = A** · **65-79 = B** · **50-64 = C** · **0-49 = D**.
La classe D non indica "inutile": indica scheda da arricchire prima dell'approccio commerciale.

## Stato della copertura (tranche 1)

- **189 prospect manuali** validati (da 193 estratti, 4 duplicati fusi) — base fissa
- **15/20 regioni** toccate, **57 comuni/località** distinti, 23/24 categorie popolate
- 71% con almeno un contatto diretto (telefono e/o email pubblici)
- Shortlist commerciale: **1 A+ · 13 A · 21 B**
- Il sistema H24 **aggiunge** schede `provenienza: automatica` senza toccare le schede esistenti
- Regioni ancora da avviare: **Marche (parziale), Umbria, Abruzzo, Basilicata, Valle d'Aosta**
- Top A+ della tranche: *Bolle & Cucce* (Empoli) — scheda completa di sito, email, telefono, FB, referente e segnali operativi.

Vedi `registry.md` per le combinazioni completate e la coda dei prossimi obiettivi.

## Compliance (avvertenze per la fase di contatto)

- I dati sono **esclusivamente pubblici**, raccolti da risultati di ricerca e directory:
  busta paga del trattamento in chiave GDPR è il possibile *legittimo interesse* B2B, da
  valutare caso per caso (soprattutto per ditte individuali, dove il dato aziendale coincide
  col dato personale).
- La raccolta è separata dal contatto (regola 11): **nessun messaggio è stato inviato**.
- Prima di campagne di contatto: rispettare ToS delle directory, verificare eventuali
  registri di opposizione, rispettare le cancellazioni, preferire PEC/email istituzionali
  dove disponibili, e includere sempre possibilità di opt-out.
- Le voci marcate `da verificare` / `da confermare` in `notes` devono essere validate prima dell'uso.
