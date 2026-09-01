# PetNote — Database Nazionale Prospect (settore pet)

Database progressivo di potenziali partner commerciali PetNote, organizzato per
**categoria → regione → provincia → città → attività → contatti → qualità → score → priorità**.

Sessione corrente: prima tranche operativa (10 ondate di ricerca), focalizzata su città
**medio-piccole e comuni**, come da direttiva (niente concentrazione sulle sole grandi città).

---

## Struttura

```
prospecting/
├── README.md                    ← questo file (metodo, rubriche, compliance)
├── registry.md                  ← registro ricerca continua (categoria × città completate)
├── process.py                   ← pipeline: normalizza → deduplica → scoring → output
├── raw/                         ← estratti grezzi per ondata (fonte primaria dichiarata per ogni riga)
│   ├── wave01_altamura.json
│   ├── wave02_faenza.json
│   ├── wave03_empoli.json
│   ├── wave04_alba.json
│   ├── wave05_acireale.json
│   ├── wave06_quartu.json
│   ├── wave07_bassano.json
│   ├── wave08_tivoli.json
│   ├── wave09_campobasso_tropea.json
│   └── wave10_roma_ospedali.json
└── output/
    ├── petnote_prospects.json   ← DATABASE FINALE (schema completo, null per dati mancanti)
    └── petnote_prospects.csv    ← stessa vista, per fogli di calcolo / CRM
```

Rigenera gli output dopo ogni nuova ondata:

```bash
python3 prospecting/process.py
```

---

## Metodo di raccolta

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
source_url, data_quality (0-100), score (0-100), priority (A+/A/B/C/D), notes`.

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

- **189 prospect** validati (da 193 estratti, 4 duplicati fusi)
- **15/20 regioni** toccate, **57 comuni/località** distinti, 23/24 categorie popolate
- 71% con almeno un contatto diretto (telefono e/o email pubblici)
- Shortlist commerciale: **1 A+ · 13 A · 21 B**
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
