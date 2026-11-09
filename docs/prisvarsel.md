# Prisvarsel – Samsung-TV-er til Black Friday

Push-varsel på ntfy (samme topic som vin- og billettvarslene) når en TV på
ønskelista når «god pris» eller «knallpris», eller faller merkbart. Alle priser
som leses, logges.

## Modellene

| TV | God pris | Knallpris | Varianter (Prisjakt) |
| --- | --- | --- | --- |
| QN70F 75" | ≤ 10 990 | ≤ 9 990 | [QE75QN70F](https://www.prisjakt.no/product.php?p=14816418), [TQ75QN70F](https://www.prisjakt.no/product.php?p=14591124) |
| M80H 75" | ≤ 10 990 | ≤ 9 990 | [TU75M80HAUXXC](https://www.prisjakt.no/product.php?p=16566935) |
| QN80F 75" | ≤ 12 990 | ≤ 11 990 | [TQ75QN80F](https://www.prisjakt.no/product.php?p=14585971), [QE75QN80F](https://www.prisjakt.no/product.php?p=15123903) |
| QN80H 75" (QN82H/QN84H) | ≤ 11 990 | ≤ 10 990 | QE75QN80HAUXXH, TQ75QN82HBUXNA, TQ75QN84HBUXNA – **mangler URL** |

Samsung selger samme TV under flere modellkoder (TQ…, QE…, TU…, UE…), og
Prisjakt har én side per kode. Hver kode følges derfor for seg, med modellens
grenser.

**Mangler:** Jeg fant ingen Prisjakt-produktsider for QN80H, QN82H eller
QN84H i 75", og heller ikke for UE75M80HAUXXH. Søk opp modellen på Prisjakt,
åpne produktsiden og lim inn lenken (`https://www.prisjakt.no/product.php?p=…`)
i `url`-feltet i `data/tv_watchlist.json`. Varianter uten URL hoppes over.

## Ønskelista

`data/tv_watchlist.json` – rediger rett i GitHub:

```json
{
  "modell": "QN70F 75\"",
  "god_pris": 10990,
  "knallpris": 9990,
  "varianter": [
    {"kode": "QE75QN70F", "url": "https://www.prisjakt.no/product.php?p=14816418"}
  ]
}
```

`url` kan også være en produktside hos Elkjøp, Power, Komplett o.l. Da leses
prisen rett fra butikken i stedet for via Prisjakt.

## Når det varsles

- 🔥 **Knallpris** (prioritet *urgent*) og ✅ **God pris** (prioritet *high*).
  Ett varsel per nivå. Nytt varsel kommer hvis prisen faller videre, går fra
  god pris til knallpris, eller har vært over grensen igjen i mellomtiden.
- 📉 **Prisfall** på minst `MIN_DROP_PCT` prosent (standard 3) siden forrige
  kjøring, med 🏆 hvis det er den laveste prisen varsleren har sett.

Varselet åpner produktsiden når du trykker på det.

## Prisloggen

`data/tv_price_log.csv` får én rad per variant per kjøring:

```
tidspunkt,modell,kode,pris,niva,url
2026-11-10T08:17:42+00:00,"QN70F 75""",QE75QN70F,12176,,https://www.prisjakt.no/product.php?p=14816418
```

`niva` er `god`, `knall` eller tom. Tidspunktet er i UTC. Fila kan åpnes
rett i Excel/Numbers eller vises på GitHub.

## Hvor fersk er prisen?

Prisjakt oppdaterer vanligvis pris og lagerstatus tre til fem ganger i døgnet,
og viser prisene uten frakt. Varsleren sjekker hver time og henger derfor ikke
etter Prisjakt, men en butikk kan ha endret prisen flere timer før Prisjakt får
det med seg. Sjekk alltid prisen i butikken før du kjøper.

## Hvordan det virker

`check_prices.py` henter hver side og leser prisen fra strukturdataene
(schema.org JSON-LD) som nettbutikker legger inn for søkemotorer. Dermed kan
samme kode brukes for alle butikker. Siste pris og varslingsstatus lagres i
`data/tv_prices_state.json`.

Sikkerhetsnett:

- Bare sidens hovedprodukt telles, ikke tilbehør eller «lignende produkter».
- Et prisfall på over 60 % regnes som en lesefeil. Det varsles ikke og logges
  ikke.
- Får vi 403/429 eller en captcha-side, hopper vi over varianten uten å
  varsle. Sperren skal ikke omgås. Kommer det mange slike, skal frekvensen ned.
- Klarer vi ikke lese en eneste pris, feiler kjøringen, og det kommer et
  «Prisvarsleren feilet»-varsel.

## Kjøring

Workflowen *Prisvarsler (TV)* går én gang i timen fra kl. 06 til 23. Den kan
også startes manuelt; med *Dump html* skrives starten av siden ut i loggen.

Tester: `python3 tests/test_prices.py`

Etter Black Friday kan workflowen slås av under *Actions → Prisvarsler (TV) →
⋯ → Disable workflow*.
