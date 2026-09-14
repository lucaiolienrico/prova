# Tag OSM per verticale

Mappatura pronta all'uso. Copia la sezione `tags_osm` nel `config.json` per il settore target. Verifica sempre con una query di test prima del run completo — la copertura OSM varia per zona.

## Veterinari e pet care

```json
"tags_osm": [
  { "key": "amenity", "value": "veterinary" },
  { "key": "shop", "value": "pet" },
  { "key": "shop", "value": "pet_grooming" },
  { "key": "amenity", "value": "animal_shelter" },
  { "key": "amenity", "value": "animal_boarding" }
]
```

## Ristorazione

```json
"tags_osm": [
  { "key": "amenity", "value": "restaurant" },
  { "key": "amenity", "value": "cafe" },
  { "key": "amenity", "value": "bar" },
  { "key": "amenity", "value": "fast_food" },
  { "key": "cuisine", "value": "*" }
]
```

## Immobiliare

```json
"tags_osm": [
  { "key": "office", "value": "estate_agent" },
  { "key": "shop", "value": "real_estate" }
]
```

Nota: la copertura OSM per agenzie immobiliari è generalmente più debole rispetto ad altri settori — valutare fonti aggiuntive.

## Estetica e benessere

```json
"tags_osm": [
  { "key": "shop", "value": "hairdresser" },
  { "key": "shop", "value": "beauty" },
  { "key": "shop", "value": "massage" },
  { "key": "leisure", "value": "spa" },
  { "key": "shop", "value": "tattoo" }
]
```

## Sanità privata (dentisti, medici, specialisti)

```json
"tags_osm": [
  { "key": "amenity", "value": "dentist" },
  { "key": "amenity", "value": "doctors" },
  { "key": "healthcare", "value": "physiotherapist" },
  { "key": "healthcare", "value": "psychotherapist" },
  { "key": "healthcare", "value": "clinic" }
]
```

## Fitness e sport

```json
"tags_osm": [
  { "key": "leisure", "value": "fitness_centre" },
  { "key": "sport", "value": "yoga" },
  { "key": "leisure", "value": "sports_centre" },
  { "key": "shop", "value": "sports" }
]
```

## Ospitalità

```json
"tags_osm": [
  { "key": "tourism", "value": "hotel" },
  { "key": "tourism", "value": "guest_house" },
  { "key": "tourism", "value": "apartment" },
  { "key": "tourism", "value": "hostel" }
]
```

## Servizi legali e professionali

```json
"tags_osm": [
  { "key": "office", "value": "lawyer" },
  { "key": "office", "value": "accountant" },
  { "key": "office", "value": "notary" },
  { "key": "office", "value": "consulting" }
]
```

## Automotive

```json
"tags_osm": [
  { "key": "shop", "value": "car_repair" },
  { "key": "shop", "value": "car" },
  { "key": "shop", "value": "tyres" },
  { "key": "amenity", "value": "fuel" }
]
```

## Edilizia e artigianato

```json
"tags_osm": [
  { "key": "office", "value": "construction_company" },
  { "key": "craft", "value": "electrician" },
  { "key": "craft", "value": "plumber" },
  { "key": "craft", "value": "carpenter" },
  { "key": "shop", "value": "hardware" }
]
```

## Come trovare tag per un settore non elencato

1. Vai su [taginfo.openstreetmap.org](https://taginfo.openstreetmap.org) e cerca la parola chiave del settore in inglese.
2. Ordina per "count" per vedere il tag più diffuso — è quello con più copertura reale sulla mappa.
3. Testa la combinazione su [overpass-turbo.eu](https://overpass-turbo.eu) prima di metterla in config, disegnando un'area di test sulla mappa.
4. Query minima di verifica:
   ```
   [out:json][timeout:25];
   area["name"="NomeComune"]->.a;
   (
     node["TAG_KEY"="TAG_VALUE"](area.a);
   );
   out body;
   ```
