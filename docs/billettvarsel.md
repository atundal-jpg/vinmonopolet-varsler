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
2. Gjør HTML-en om til tekstlinjer og leser ut mønsteret
   «kamptittel → dag/dato/arena → *N tickets*» (også norsk: *N billetter*).
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

GitHub Actions-workflowen `Billettvarsler (fotball)` kjører hvert 15. minutt
hele døgnet, med én sjekk per kjøring. Tettere polling ble prøvd (hvert minutt),
og resultatet var at siden svarte med venterom og captcha i stedet for
billetter – sjeldnere sjekker som slipper gjennom gir altså bedre varsling enn
hyppige som blir avvist.

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

## Verifiser parseren mot ekte side

Parseren er testet mot markup som tilsvarer det siden viser («Norway vs
Denmark … 0 tickets»), men er ennå ikke bekreftet mot ekte HTML: første kjøring
kom bare fram til cookie-veggen og venterommet. Kjør workflowen manuelt med
**Dump html** huket av (Actions → Billettvarsler (fotball) → Run workflow) og se
i loggen hva som faktisk kommer inn:

- kampnavn og «N tickets» → parseren treffer, alt er i orden
- «🚧 Kom ikke gjennom» → siden sperrer oss; senk frekvensen ytterligere
- andre linjer → `parse_availability()` må tilpasses; loggen viser nøyaktig de
  linjene funksjonen får inn

## Vær grei mot siden

Venterommet og captchaen er sidens grense for automatisk trafikk. Varsleren
respekterer den: den løser ingen captcha, den prøver ikke å komme rundt
venterommet, og den sjekker sjelden nok til å ikke belaste siden. Varselet er
ment å gi *deg* beskjed om å gå inn og kjøpe – ikke å kapre billetter automatisk.
