# REPORT D'USO — Database Prospect PetNote (tranche 1)

**Data:** 1 settembre 2026 · **Stato:** lavoro concluso e versionato (branch `arena/01a05c27-prova`)
**Pacchetto:** cartella `prospecting/` — 189 prospect · 15 regioni · 57 comuni · 23 categorie

---

## 1. Cosa hai ricevuto

| File | Uso |
|---|---|
| `prospecting/output/petnote_prospects.csv` | **Il database da usare ogni giorno** (Excel/LibreOffice/Google Sheets/CRM). Delimitatore `;` (standard Excel italiano). |
| `prospecting/output/shortlist_AB.csv` | **La lista d'azione immediata**: solo i 35 prospect A+/A/B, ordinati per punteggio. |
| `prospecting/output/petnote_prospects.json` | Stesso database in formato tecnico (importazione CRM via API, script). |
| `prospecting/output/riepilogo.txt` | Fotografia statistica corrente. |
| `prospecting/registry.md` | Dove la ricerca è già stata fatta (da NON ripetere) e cosa fare dopo. |
| `prospecting/raw/*.json` | Fonti primarie per ondata, con URL di provenienza di ogni dato. |

> ⚠️ I file in `output/` sono **rigenerati** dalla pipeline: non modificarli a mano. Le modifiche si fanno nei `raw/` o in `config.json`.

## 2. Come leggere una scheda

Ogni riga contiene: identità (`business_name`, `category`, `subcategory`), geografia
(`city`, `province`, `region`), contatti pubblici (`address`, `website`, `email`, `phone`,
`instagram_*`, `facebook_url`, `contact_name`), tracciabilità (`source`, `source_url`),
valutazione (`data_quality` 0-100, `score` 0-100, `priority`) e `notes`.

- **`null` = informazione non trovata pubblicamente.** Non è mai stata inventata.
- **`data_quality`**: quanto la scheda è completa (13 campi). Utile per sapere *quanto ti manca da sapere*.
- **`score` / `priority`**: quanto il prospect vale commercialmente per PetNote:

| Priorità | Score | Significato operativo |
|---|---|---|
| **A+** | 90-100 | Scheda completa, digitalizzata, alto potenziale: contatto prioritario |
| **A** | 80-89 | Ottimo prospect: contatto diretto possibile subito |
| **B** | 65-79 | Buono: valido per campagne mirate per categoria/zona |
| **C** | 50-64 | Contactabile ma scarno: verifica rapida prima dell'azione |
| **D** | 0-49 | Solo traccia: arricchire i dati prima di usarla |

- **`notes`**: il campo più importante dopo i contatti. Contiene segnali operativi
  (orari, recensioni, WhatsApp, catene) e **avvertenze** (`da verificare`, `da confermare`,
  `Fonte del 2016/2018`, fusioni fatte in deduplica).

## 3. Uso operativo consigliato

### 3.1 Fase 1 — Contatto diretto (settimane 1-2)
Lavora **`shortlist_AB.csv`** dall'alto verso il basso. Già pronta: 35 attività con
telefono e/o email pubblici. Angolo commerciale per categoria:

| Categoria | Leva PetNote suggerita |
|---|---|
| Veterinari / Cliniche / Ambulatori / Ospedali | Continuità clinica digitale, libretto sanitario condiviso, promemoria vaccini e terapie (es. Polivet H24, Amb. Cocca, Amb. Festa con visite comportamentali) |
| Rifugi / Canili / Associazioni | Scheda sanitaria dell'adottato consegnata al nuovo proprietario; donazioni/adozioni a distanza (es. ALFA con 400 adozioni/5 anni col Comune di Tivoli, Aristogatti 16.000 follower) |
| Toelettature / Pet shop (indipendenti) | QR su scontrino o sito → scheda PetNote del cliente; incrocio con promemoria salute (es. Bolle & Cucce, Palla di Pelo con consegne a domicilio) |
| Centri cinofili / Educatori / Addestratori | Diario di educazione condiviso proprietario-educatore; corsi (es. Striulli, Il Lupo con consulenze post-affido) |
| Pensioni / Pet hotel | Diario del soggiorno con aggiornamenti al proprietario (es. Qua La Zampa con navetta, Animalife) |
| Allevamenti | Documentazione del cucciolo (vaccini, pedigree, sverminazioni) ceduta al compratore |
| Fisioterapisti veterinari | Percorsi di riabilitazione tracciati (lead raro: Animal Wellness, Alba — da arricchire) |
| Pet shop di catena (Arcaplanet, Maxi Zoo, Conad) | **Non contattare il punto vendita**: va alla direzione nazionale (segnato nelle `notes`) |
| Dog/cat sitter via piattaforma (Cronoshare, Pawshake) | Contattabili solo dentro la piattaforma: usare per campagne dedicate |

### 3.2 Fase 2 — Verifica rapida (parallela)
- Tooltip di controllo: cerca in `notes` le parole `da verificare` / `da confermare` /
  `da integrare` → quei dati vanno validati (telefonata o sito) **prima** dell'uso.
- Schede con `Fonte del 2016/2018` → verificare che l'attività sia ancora operativa.
- In Excel: filtro su `notes` → "contiene: da verificare".

### 3.3 Fase 3 — Arricchimento (classi C/D)
Le 154 schede C/D sono piste territoriali (nome + indirizzo/città) da trasformare in
prospect: cercare sito/social, aggiungere contatti nel `raw/` corrispondente e rilanciare
la pipeline (lo score sale da solo).

### 3.4 Copertura nuove zone
Sequenza suggerita (in `registry.md`): Umbria, Abruzzo, Basilicata, Valle d'Aosta (regioni
mancanti) → poi province della direttiva non toccate (cintura MI, NA, Bari città, Bologna…).

## 4. Come aggiornare il database

```bash
# 1) aggiungi una nuova ondata (copia il formato dei file esistenti)
prospecting/raw/wave11_spoleto.json

# 2) rilancia la pipeline (normalizza, deduplica, riscore, rigenera tutti gli output)
python3 prospecting/process.py

# 3) aggiorna prospecting/registry.md con le combinazioni completate
```

Modello di riga grezza (lasciare `null` ciò che non trovi):

```json
{"n":"Nome attività","cat":"Toelettature","sub":null,"city":"Spoleto","prov":"PG","reg":"Umbria",
 "addr":null,"site":null,"email":null,"tel":null,"ig":null,"fb":null,"other":null,
 "contact":null,"src":"Fonte","srcurl":"https://...","desc":"","notes":null}
```

Modifiche fini allo scoring senza toccare codice: **`prospecting/config.json`**
(punteggi base per categoria, pesi per contatto, soglie A+/A/B/C, nomi dei file di output).

Filtro rapido da terminale (esempio: contattabili A/B in Puglia):

```bash
python3 -c "import json;d=json.load(open('prospecting/output/petnote_prospects.json'));[print(r['business_name'],'|',r['phone'],'|',r['email']) for r in d if r['region']=='Puglia' and r['priority'] in ('A+','A','B')]"
```

## 5. Regole di igiene prima del contatto (compliance)

1. Solo dati pubblici, ricerca **separata** dal contatto (nessun invio automatico è stato fatto).
2. Attenzione GDPR: per ditte individuali il recapito aziendale è dato personale → usare
   base di legittimo interesse B2B, oggetto pertinente, opt-out sempre presente.
3. Rispettare le ToS delle directory (PagineGialle/Bianche ecc.): il riferimento in `source_url`
   serve anche a mostrare la provenienza lecita del dato.
4. Registrare e onorare subito eventuali richieste di cancellazione.
5. Non usare email "uzzate" o ricostruite: se non pubblica, resta `null` (regola aurea del progetto).

## 6. Manutenzione consigliata

- **Settimanale**: 2-3 nuove ondate (città piccole) → pipeline → aggiorna shortlist.
- **Mensile**: ri-verifica contatti scaduti nelle schede con fonte datata; marcatura esiti contatto.
- **Trimestrale**: re-run completo, pulizia duplicati residui, revisione pesi in `config.json`.

---

**Stato finale tranche 1:** 189 prospect · 135 contattabili (71%) · 35 in shortlist operativa ·
top A+ = Bolle & Cucce (Empoli, 97/100). Coperte 15/20 regioni e 57 comuni, con priorità
documentata a città medio-piccole e località turistiche (Ricadi/Costa degli Dei, Tropea area,
Alghero, Vezza d'Alba…).
