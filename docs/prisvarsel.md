# Prisvarsel – Samsung-TV-er til Black Friday

Push-varsel på ntfy (samme topic som vin- og billettvarslene) når en TV på
ønskelista blir billigere.

## Ønskelista

`data/tv_watchlist.json` – rediger rett i GitHub:

```json
[
  {
    "navn": "Samsung S90H 65\" OLED (2026)",
    "url": "https://www.prisjakt.no/product.php?p=16030853",
    "malpris": 18990
  }
]
```

- **url** – helst en Prisjakt-produktside, som gir laveste pris på tvers av
  butikker. En produktside hos Elkjøp, Power, Komplett o.l. går også.
- **malpris** – prisen du ville slått til på. Kan utelates; da varsles det
  bare ved prisfall.

Startlista har tre 65"-modeller fra 2026. Målprisene er satt litt under
laveste pris på Prisjakt i begynnelsen av november, og er bare et utgangspunkt.

| Modell | Prisjakt | Målpris |
| --- | --- | --- |
| S90H 65" OLED | [p=16030853](https://www.prisjakt.no/product.php?p=16030853) | 18 990 |
| S95H 65" OLED | [p=16030722](https://www.prisjakt.no/product.php?p=16030722) | 19 990 |
| The Frame Pro 65" | [p=16511197](https://www.prisjakt.no/product.php?p=16511197) | 17 990 |

## Når det varsles

- 🎯 **Målpris nådd** (høy prioritet). Bare én gang per prisnivå: nytt varsel
  kommer hvis prisen faller videre, eller hvis den først har vært over
  målprisen igjen.
- 📉 **Prisfall** på minst `MIN_DROP_PCT` prosent (standard 3) siden forrige
  kjøring, med 🏆 hvis det er den laveste prisen varsleren har sett.

Varselet åpner produktsiden når du trykker på det.

## Hvordan det virker

`check_prices.py` henter hver side og leser prisen fra strukturdataene
(schema.org JSON-LD) som nettbutikker legger inn for søkemotorer. Dermed kan
samme kode brukes for alle butikker. Prisene lagres i
`data/tv_prices_state.json`.

Sikkerhetsnett:

- Bare sidens hovedprodukt telles, ikke tilbehør eller «lignende produkter».
- Et prisfall på over 60 % regnes som en lesefeil og ignoreres.
- Får vi 403/429 eller en captcha-side, hopper vi over varen uten å varsle.
  Sperren skal ikke omgås. Kommer det mange slike, skal frekvensen ned.
- Klarer vi ikke lese en eneste pris, feiler kjøringen, og det kommer et
  «Prisvarsleren feilet»-varsel.

## Kjøring

Workflowen *Prisvarsler (TV)* går én gang i timen fra kl. 06 til 23. Den kan
også startes manuelt; med *Dump html* skrives starten av siden ut i loggen.

Tester: `python3 tests/test_prices.py`

Etter Black Friday kan workflowen slås av under *Actions → Prisvarsler (TV) →
⋯ → Disable workflow*.
