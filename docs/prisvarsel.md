# Prisvarsel – Samsung-TV-er til Black Friday

Push-varsel på ntfy (samme topic som vin- og billettvarslene) når en TV på
ønskelista når «god pris» eller «knallpris», eller faller merkbart. Alle priser
som leses, logges. Butikkenes egne sider sjekkes hvert 5. minutt, Prisjakt hver
time.

## Modellene

| TV | God pris | Knallpris | Butikker (hvert 5. min) | Prisjakt (hver time) |
| --- | --- | --- | --- | --- |
| QN70F 75" | ≤ 10 990 | ≤ 9 990 | Komplett, NetOnNet, Elon, Elkjøp¹ | TQ75QN70F, QE75QN70F² |
| M80H 75" | ≤ 10 990 | ≤ 9 990 | Elkjøp, Power, Komplett | TU75M80HAUXXC |
| QN80F 75" | ≤ 12 990 | ≤ 11 990 | NetOnNet, Elkjøp | TQ75QN80F, QE75QN80F² |
| QN80H 75" (QN82H/QN84H) | ≤ 11 990 | ≤ 10 990 | Elkjøp (QN84H)³, Samsung.no (QN82H) | – |

¹ Var ikke tilgjengelig i november, men følges i tilfelle den kommer tilbake.
² Importvariant (QE). De nordiske modellene har TQ/TU-koder.
³ Lenken er satt sammen fra Elkjøps varenummer 1082827 og ikke bekreftet.
   Står det «fant ingen pris» i loggen, søk på «QN84H» hos Elkjøp og bytt lenken.

Samsung selger samme TV under flere modellkoder (TQ…, QE…, TU…), og Prisjakt
har én side per kode. Hver side følges for seg, med modellens grenser.
Lenkene står i `data/tv_watchlist.json`. Feltet `merknad` er bare til
informasjon.

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

## Legge inn butikkenes egne sider

Samme kode kan stå flere ganger, én gang per butikk. Butikken kjennes igjen fra
domenet (Elkjøp, Power, Komplett, NetOnNet, Elon), eller kan settes med
`"butikk"`:

```json
"varianter": [
  {"kode": "QE75QN70F", "url": "https://www.prisjakt.no/product.php?p=14816418"},
  {"kode": "QE75QN70F", "url": "https://www.elkjop.no/product/…"},
  {"kode": "QE75QN70F", "url": "https://www.power.no/…"}
]
```

Slik finner du lenkene via Prisjakt:

1. Åpne Prisjakt-siden for modellen og klikk deg videre til butikken.
2. **Kopier adressen fra adressefeltet når butikkens side har lastet**, ikke
   lenken på Prisjakt. «Til butikken»-lenkene er klikk som butikkene betaler
   Prisjakt for. Ble de brukt hvert 5. minutt, ville butikkene betalt for
   hundrevis av falske klikk. Skriptet nekter derfor slike lenker.
3. Sporingsparametre som `utm_source` og `gclid` fjernes automatisk.

Står ikke butikken på Prisjakt, søk opp TV-en hos butikken direkte. Sjekk at
modellkoden på siden stemmer, for eksempel QE75QN70F og ikke QE65QN70F.

## Når det varsles

Det finnes to typer varsel, og de skal være lette å skille fra hverandre:

**1. Innenfor grensene – det tydelige varselet**

```
🔥 KNALLPRIS – QN70F 75": 9 790 kr hos Komplett
🔥 KNALLPRIS! Innenfor grensen din på 9 990 kr (200 kr under).
📉 Ned 1 700 kr (15 %) fra 11 490 kr
💡 Elkjøp kan matche prisen (prismatch) …
```

- 🔥 **KNALLPRIS** har prioritet *urgent*, som i ntfy-appen gir lang
  vibrasjon og lyd og bryter gjennom «Ikke forstyrr» hvis du tillater det.
- ✅ **GOD PRIS** har prioritet *high*, med vibrasjon og lyd.
- Grensen står først både i tittelen og i teksten, og varselet har en knapp
  rett til butikken.
- Ett varsel per nivå. Nytt varsel kommer hvis prisen faller videre, går fra
  god pris til knallpris, eller har vært over grensen igjen i mellomtiden.

**2. Prisfall – vanlig varsel**

```
📉 Prisfall – QN70F 75": 11 490 kr hos Komplett
500 kr igjen til god pris (10 990 kr).
📉 Ned 500 kr (4 %) fra 11 990 kr
```

- Normal prioritet, når prisen faller minst `MIN_DROP_PCT` prosent (standard 1)
  siden forrige sjekk, uten å ha nådd et nytt nivå.
- Viser hvor langt det er igjen til god pris eller knallpris, og 🏆 hvis det
  er den laveste prisen varsleren har sett.
- Blir det for mange, kan terskelen settes opp med repository-variabelen
  `MIN_DROP_PCT`.

Varselet åpner produktsiden når du trykker på det.

**Prismatch:** Når en god pris eller knallpris er funnet hos Komplett,
NetOnNet, Skousen eller Power, minner varselet om at Elkjøp kan matche prisen.
Er det Elkjøp som er billigst, minner varselet om at Power matcher Elkjøp.
Vilkårene kan endre seg, så sjekk dem
([Elkjøp](https://www.elkjop.no/kundeservice/prismatch),
[Tek.no](https://www.tek.no/nyheter/guide/i/V9AJop/store-forskjeller-for-prismatch)).

## Prisloggen

`data/tv_price_log.csv` får én rad per side hver gang prisen leses:

```
tidspunkt,modell,kode,butikk,pris,niva,url
2026-11-10T08:17:42+00:00,"QN70F 75""",QE75QN70F,Prisjakt,12176,,https://www.prisjakt.no/product.php?p=14816418
```

`niva` er `god`, `knall` eller tom. Tidspunktet er i UTC. Fila kan åpnes
rett i Excel/Numbers eller vises på GitHub.

## Hvor fersk er prisen?

Prisjakt oppdaterer vanligvis pris og lagerstatus tre til fem ganger i døgnet,
og viser prisene uten frakt. Prisjakt-sider sjekkes derfor bare hver time,
siden oftere ikke gir noe. **Butikkenes egne sider sjekkes hvert 5. minutt**
og fanger prisendringer med en gang. Sjekk alltid prisen i butikken før du
kjøper.

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

Workflowen *Prisvarsler (TV)* går døgnet rundt. GitHub starter planlagte
kjøringer i praksis bare hver 30.–60. minutt. Derfor looper hver kjøring i
inntil 50 minutter og sjekker selv det som er forfalt: butikksider hvert 5.
minutt og Prisjakt hver time. Intervallene kan endres med repository-variablene
`STORE_INTERVAL_MIN` og `PRISJAKT_INTERVAL_MIN` (Settings → Secrets and
variables → Variables). Tilstand og logg lagres etter hver runde og pushes når
kjøringen er ferdig.

Workflowen kan også startes manuelt. Med *Dump html* gjør den én runde og
skriver starten av hver side ut i loggen.

Det blir 12 forespørsler i timen per butikkside, spredt over flere butikker.
Viser loggen mange «🚧 kom ikke inn», skal intervallet opp.

Tester: `python3 tests/test_prices.py`

Etter Black Friday kan workflowen slås av under *Actions → Prisvarsler (TV) →
⋯ → Disable workflow*.
