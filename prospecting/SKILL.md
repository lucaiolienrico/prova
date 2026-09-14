---
name: h24-prospecting-engine
description: Skill obbligatoria per configurare, adattare o eseguire il debug del sistema H24 Prospecting Engine — motore di lead generation automatica basato su OpenStreetMap e GitHub Actions. Attivare SEMPRE quando la richiesta riguarda config.json, tag OSM/Overpass, verticalizzazione del sistema su una nuova categoria (veterinari, ristoranti, immobiliare, estetica, dentisti, palestre, hotel, legale, automotive, edilizia o qualsiasi altro settore), scoring dei prospect, workflow GitHub Actions del prospecting, deduplica contatti, o troubleshooting di run falliti. Non ignorare questa skill nemmeno per modifiche "piccole" al config — i tag OSM sbagliati producono risultati vuoti o rumorosi.
---

# H24 Prospecting Engine

Sistema di lead generation automatica: interroga OpenStreetMap via Overpass API su base geografica (comuni/città), estrae attività commerciali per categoria, deduplica, assegna uno score e pubblica l'output via commit automatico. Gira interamente su GitHub Actions — nessun server, nessun costo di infrastruttura.

Questa skill copre **qualsiasi verticale**: il sistema è agnostico rispetto al settore, cambia solo `config.json`.

## Architettura in breve

```
cron GitHub Actions (ogni N ore)
    └─ find_candidates.py → interroga Overpass API per i tag definiti in config.json
          └─ 5 controlli anti-duplicato (ID OSM, email, telefono, sito, nome+città fuzzy)
    └─ process.py → scoring + shortlist per fascia (A+/A/B/C/D)
    └─ git commit + push automatico su main
```

File chiave:
- `prospecting/config.json` — **unico file da modificare per cambiare verticale**
- `prospecting/find_candidates.py` — motore di query ed estrazione
- `prospecting/process.py` — scoring e generazione output
- `prospecting/queue/cities.json` — coda comuni da processare
- `prospecting/state/progress.json` — stato di avanzamento
- `prospecting/output/` — JSON + CSV + shortlist generati
- `.github/workflows/*.yml` — definizione del cron

## Configurare un nuovo verticale

Passi, in ordine:

1. **Identifica i tag OSM della categoria target.** Vedi `references/categorie-osm.md` per una mappatura pronta di 10+ settori. Se il settore non è coperto, cerca su [taginfo.openstreetmap.org](https://taginfo.openstreetmap.org) il tag più usato per quella categoria.
2. **Aggiorna `config.json`** con i tag scelti (vedi struttura sotto).
3. **Verifica con una query di test** su un singolo comune prima di lanciare il run completo — evita di consumare la quota Overpass su una config sbagliata.
4. **Regola i pesi di scoring** se la categoria ha priorità diverse (es. presenza sito web più importante per servizi digitali, presenza telefono più importante per servizi locali walk-in).
5. **Lancia il workflow manualmente** una volta (GitHub → Actions → Run workflow) prima di affidarti al cron.

### Struttura config.json

```json
{
  "categoria": "nome_leggibile_categoria",
  "tags_osm": [
    { "key": "amenity", "value": "veterinary" },
    { "key": "shop", "value": "pet" }
  ],
  "raggio_ricerca_km": 5,
  "scoring": {
    "peso_email": 30,
    "peso_telefono": 25,
    "peso_sito_web": 20,
    "peso_indirizzo_completo": 15,
    "peso_orari_pubblicati": 10
  },
  "soglie_fascia": {
    "A_plus": 85,
    "A": 70,
    "B": 50,
    "C": 30
  }
}
```

Non serve toccare `find_candidates.py` o `process.py` per un cambio di verticale — leggono tutto da qui.

## Deduplica

5 controlli, in quest'ordine di priorità (il primo match vince):
1. ID OSM identico (stesso nodo/way già processato)
2. Email identica (case-insensitive, trim)
3. Telefono identico (normalizzato: solo cifre, prefisso internazionale rimosso)
4. Sito web identico (dominio normalizzato, senza www/http)
5. Nome + città con fuzzy match (soglia similarità configurabile, default 90%)

Se un run produce troppi falsi duplicati, alza la soglia fuzzy. Se produce troppi doppioni reali, abbassala.

## Scoring e shortlist

Ogni prospect riceve un punteggio 0-100 sommando i pesi configurati per ogni campo presente. Le fasce (`A+/A/B/C/D`) sono soglie sul punteggio totale, configurabili in `soglie_fascia`.

La shortlist (`output/shortlist_AB.csv`) contiene solo fasce A+/A/B — i prospect con dati sufficienti per un contatto diretto immediato.

## Deploy e attivazione

```bash
git clone <repo>
cd <repo>
# modifica prospecting/config.json per il verticale target
git add prospecting/config.json
git commit -m "config: verticalizzazione su <categoria>"
git push
```

Il cron è già definito in `.github/workflows/` — non richiede setup aggiuntivo. Per un primo run immediato: GitHub → tab Actions → seleziona il workflow → **Run workflow**.

## Troubleshooting comuni

| Sintomo | Causa probabile | Fix |
|---|---|---|
| Run completa ma 0 prospect trovati | Tag OSM sbagliati o inesistenti per l'area | Verifica il tag su taginfo.openstreetmap.org, testa la query su [overpass-turbo.eu](https://overpass-turbo.eu) |
| Troppi risultati irrilevanti | Tag troppo generico (es. `shop=yes`) | Usa combinazioni di tag più specifiche |
| Run fallisce con timeout | Overpass API sovraccarica o raggio troppo ampio | Riduci `raggio_ricerca_km`, aggiungi retry con backoff |
| Duplicati non rilevati | Dati sorgente incoerenti (stesso posto, nomi diversi) | Abbassa soglia fuzzy match nome+città |
| Commit automatico non parte | Permessi del workflow su `GITHUB_TOKEN` insufficienti | Verifica che il workflow abbia `contents: write` nei permessi |

## Limiti e note operative

- Dati da OpenStreetMap, licenza **ODbL** — uso commerciale consentito, redistribuzione del dataset grezzo richiede share-alike.
- Qualità del dato dipende dalla copertura OSM dell'area — zone rurali o paesi piccoli hanno meno copertura di città grandi.
- Nessun invio di messaggi automatico incluso — il sistema produce solo il dataset, il contatto resta manuale.
- Per approfondimenti sui tag disponibili per ogni settore, vedi `references/categorie-osm.md`.
