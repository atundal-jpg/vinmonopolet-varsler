# Billettvarsel – resale.fotball.no

Varsler på ntfy (samme topic som vinvarslene) når det legges ut billetter for
videresalg på NFFs offisielle plattform.

## Hvordan det virker

`resale.fotball.no` kjører på SecuTix, og sidene er **server-rendret HTML**.
Antallet billetter per kamp ligger altså rett i markupen – ingen JavaScript,
ingen innlogging og ingen API-nøkkel trengs for å lese den. Men siden krever en
økt-cookie, og den har et **venterom med captcha** som slår inn ved hyppige
forespørsler (se «Sperrer» under). `check_tickets.py` gjør derfor:

1. Henter forsiden én gang for å få en gyldig økt-cookie, og deretter de
   overvåkede URL-ene (`RESALE_URLS`).
2. Gjør HTML-en om til tekstlinjer og leser ut billettallet per kamp. På den
   ekte siden ligger lagnavnene på hver sin linje fordi flaggbildene skiller
   dem, slik:

   ```
   Date and time:
   Sunday, 27 September 2026 - 20:45
   Venue:
   Ullevaal Stadion
   Norway
   vs
   Portugal
   0 tickets
   ```

   Kampnavnet settes sammen fra linjene rundt «vs», og dato og arena tas med
   i varselteksten.
3. Sammenligner antallet med forrige kjøring (`data/tickets_state.json`).
4. Sender push via ntfy når et antall går fra 0 til høyere – eller øker
   ytterligere, siden flere billetter ute er verdt å vite om.

Standard-URL-ene er:

- kampvalget for Mens Nations League
  (`/selection/event/date?productId=10229739619905&checkResaleAvailability=true`)
- den generelle lista over alt som ligger ute
  (`/list/resaleProducts/?lang=en`)

### Sperrer: cookie-vegg, venterom og captcha

Får vi ikke se billettsiden – fordi vi mangler økt-cookie, eller fordi siden
setter oss i venterom med captcha – logges det og kjøringen avsluttes **uten å
varsle**. Vi vet da ingenting om billettene, og et varsel ville vært en gjetning.

Captchaen omgås ikke. Den er sidens måte å si at den ikke vil ha rask
automatisk trafikk, og det respekteres: sjekkene er derfor lagt til hvert 15.
minutt, med bare én forespørsel per side per kjøring. Ser du mange
«🚧 Kom ikke gjennom»-linjer i loggen, er det frekvensen som må ned, ikke opp.

### Fallback hvis markupen endrer seg

Klarer ikke parseren å lese ut noen tall på en side vi faktisk kom gjennom til,
varsles det bare ved en reell overgang: siden sa eksplisitt «ingen billetter»,
og gjør det ikke lenger. Har vi aldri sett den teksten, logges det i stedet for
å varsle – en parser som ikke treffer skal ikke kunne sende falske alarmer.

## Kjøring

GitHub Actions-workflowen `Billettvarsler (fotball)` kjører hvert 5. minutt hele
døgnet – raskeste faste intervall Actions tilbyr – med én sjekk per side per
kjøring, og noen sekunders tilfeldig slark i starttidspunktet.

Hvorfor akkurat 5 minutter: første forsøk polte hvert minutt *uten* økt-cookie,
og da svarte siden med venterom og captcha i stedet for billetter. Etter at
cookie-håndteringen kom på plass har kjøringer med 4–6 minutters mellomrom
sluppet gjennom hver gang. Vil du prøve tettere, må det gjøres med en loop inne
i kjøringen (`POLL_INTERVAL`), og da bør du følge med i loggen: dukker det opp
«🚧 Kom ikke gjennom», er du over grensen.

### Tilbaketrekking

Sperrer siden oss likevel, pauser varsleren *seg selv* for den siden – 10
minutter første gang, så 20, 40 og opp til en time – og gjenopptar automatisk
når en sjekk slipper gjennom. Frekvensen regulerer seg altså selv mot det
siden tåler, uten at noen må gjette.

## Innstillinger

| Variabel | Hva den gjør |
| --- | --- |
| `NTFY_TOPIC` (secret) | ntfy-topic det varsles til. Samme som vinvarsleren. |
| `RESALE_URLS` (variable) | Kommaseparerte URL-er som overvåkes. Tom = standardene over. |
| `MATCH_FILTER` (variable/input) | Varsle bare for kamper som inneholder teksten, f.eks. `Portugal`. |
| `POLL_INTERVAL` / `MAX_MINUTES` | Valgfri loop inne i én kjøring (sekunder / minutter). Står på 0 – siden tåler ikke tett polling. |
| `DUMP_HTML` | `1` skriver ut sideinnholdet i loggen. |

Vil du følge en annen kamp, finn `productId` i URL-en på kampvalgsiden og legg
hele URL-en inn i `RESALE_URLS`.

## Tester

`python3 tests/test_tickets.py` kjører parseren mot linjesekvensen fra en ekte
kjøring (hentet fra Actions-loggen med `DUMP_HTML=1`), og sjekker at kampnavn og
antall leses riktig, at sperresider ikke forveksles med innhold, og at varsel
sendes én gang når billetter dukker opp – aldri på en side vi ikke kom gjennom
til. Endrer siden struktur, er `REAL_LINES` i testen det første som skal
oppdateres.

## Feilsøking mot ekte side

Kjør workflowen manuelt med **Dump html** huket av (Actions → Billettvarsler
(fotball) → Run workflow) og se i loggen hva som faktisk kommer inn:

- kampnavn og «N tickets» → parseren treffer, alt er i orden
- «🚧 Kom ikke gjennom» → siden sperrer oss; senk frekvensen ytterligere
- andre linjer → `parse_availability()` må tilpasses; loggen viser nøyaktig de
  linjene funksjonen får inn

## Vær grei mot siden

Venterommet og captchaen er sidens grense for automatisk trafikk. Varsleren
respekterer den: den løser ingen captcha, den prøver ikke å komme rundt
venterommet, og den sjekker sjelden nok til å ikke belaste siden. Varselet er
ment å gi *deg* beskjed om å gå inn og kjøpe – ikke å kapre billetter automatisk.
