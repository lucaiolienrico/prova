# H24 Prospecting Engine

> Lead generation automatica H24 — zero server, zero costi variabili, gira su GitHub Actions.

![Status](https://img.shields.io/badge/status-live-success) ![Python](https://img.shields.io/badge/Python-3.11-blue) ![License](https://img.shields.io/badge/license-Commercial-important) ![Run](https://img.shields.io/badge/run%20completati-55-brightgreen)

**[🌐 Landing page](https://lucaiolienrico.github.io/prova/)** &nbsp;·&nbsp; **[Acquista il sistema](#-prezzi)**

---

## Cosa fa

Scansiona i comuni italiani su OpenStreetMap ogni 6 ore, costruisce un database di prospect qualificati e lo commita automaticamente su GitHub. Nessun server. Nessuna VPS. Nessun cron job da gestire.

## Numeri live

| Prospect totali | Run completati | Costo infrastruttura | Comuni scansionati |
|:---:|:---:|:---:|:---:|
| **1.155** | **55** | **€0** | **280+ / 388** |

## Architettura

```
GitHub Actions (cron 00/06/12/18 UTC)
    └─ find_candidates.py
          └─ Overpass API (OpenStreetMap, licenza ODbL)
                └─ estrae POI per comune
                └─ 5 controlli anti-duplicato
    └─ process.py → scoring + shortlist A+/A/B/C/D
    └─ git commit + push automatico su main
```

## Come funziona

| Step | Cosa fa |
|---|---|
| **cron** | GitHub Actions si avvia ogni 6h (00:00, 06:00, 12:00, 18:00 UTC) |
| **query** | Interroga Overpass (OpenStreetMap) per categoria sul comune corrente |
| **dedup** | 5 controlli anti-duplicato: ID OSM, email, tel, sito, nome+città |
| **output** | JSON + CSV + shortlist scorata pushati su `main` in automatico |

## Output

```
prospecting/output/
├── petnote_prospects.json   # database completo (1.155 prospect, 930KB)
├── petnote_prospects.csv    # stesso dataset in CSV (396KB)
├── shortlist_AB.csv         # top 112 prospect A+/A/B per score
└── riepilogo.txt            # stats: regione, categoria, score
```

## Categorie prospect

| Categoria | Prospect |
|---|---|
| Veterinari | 624 |
| Pet shop | 249 |
| Toelettature | 77 |
| Rifugi/canili | 61 |
| Ambulatori | 32 |
| Pensioni animali | 27 |

## 💰 Prezzi

> Codice sorgente completo. Adattabile a qualsiasi verticale in 30 minuti.

| | Base | Pro | Agency |
|---|:---:|:---:|:---:|
| **Prezzo** | **€497** | **€897** | **€1.997** |
| Repo privata completa | ✅ | ✅ | ✅ |
| Config 1 verticale | ✅ | ✅ | ✅ |
| Guida setup PDF | ✅ | ✅ | ✅ |
| 388 comuni italiani | ✅ | ✅ | ✅ |
| Call onboarding 1h | ❌ | ✅ | ✅ |
| Config 3 verticali | ❌ | ✅ | ✅ |
| Supporto 30 giorni | ❌ | ✅ | ✅ |
| Licenza multi-cliente | ❌ | ❌ | ✅ |
| Config illimitati | ❌ | ❌ | ✅ |
| Supporto 90 giorni | ❌ | ❌ | ✅ |

**[→ Acquista ora](https://lucaiolienrico.github.io/prova/#pricing)**

## Quickstart (per acquirenti)

```bash
# 1. Clona la repo ricevuta
git clone https://github.com/TUO-USERNAME/h24-prospecting-engine.git
cd h24-prospecting-engine

# 2. Adatta il tuo verticale (l'unico file da modificare)
nano prospecting/config.json

# 3. Il workflow è già in .github/workflows/ — non serve copiarlo
# 4. Push su GitHub — il cron parte da solo
git add . && git commit -m "setup verticale" && git push

# 5. Primo run immediato (opzionale)
# GitHub → Actions → "PetNote Prospecting H24" → Run workflow
```

## Note legali

- **Dati:** OpenStreetMap, licenza [ODbL](https://opendatacommons.org/licenses/odbl/). Solo contatti B2B pubblici.
- **GDPR:** Legittimo interesse per contatti professionali pubblici. Nessun invio automatico incluso.
- **Codice:** Licenza commerciale — vietata la redistribuzione senza accordo scritto.

---

*Sistema validato su 55 run in produzione. Dati reali, non simulati.*
