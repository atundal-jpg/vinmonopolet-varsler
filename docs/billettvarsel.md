# Billettvarsel – resale.fotball.no

Varsler på ntfy (samme topic som vinvarslene) når det legges ut billetter for
videresalg på NFFs offisielle plattform.

## Hvordan det virker

`resale.fotball.no` kjører på SecuTix, og sidene er **server-rendret HTML**.
Det betyr at antallet billetter per kamp ligger rett i markupen som hentes –
ingen JavaScript, ingen innlogging og ingen API-nøkkel er nødvendig for å lese
den. `check_tickets.py` gjør derfor:

1. Henter de overvåkede URL-ene (`RESALE_URLS`).
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

### Fallback hvis markupen endrer seg

Klarer ikke parseren å lese ut noen tall, faller den tilbake på å se etter
«ingen billetter»-teksten på siden. Forsvinner den teksten, sendes et varsel om
at det *kan* ha kommet billetter ut, slik at en endring i sidestrukturen aldri
fører til at et varsel går tapt i stillhet.

## Kjøring

GitHub Actions-workflowen `Billettvarsler (fotball)` kjører hvert 5. minutt hele
døgnet, og hver kjøring sjekker fire ganger med ett minutts mellomrom
(`POLL_INTERVAL=60`, `MAX_MINUTES=4`). I praksis er vi altså innom siden omtrent
én gang i minuttet. Skru ned frekvensen ved å sette `POLL_INTERVAL: "0"` i
workflowen.

## Innstillinger

| Variabel | Hva den gjør |
| --- | --- |
| `NTFY_TOPIC` (secret) | ntfy-topic det varsles til. Samme som vinvarsleren. |
| `RESALE_URLS` (variable) | Kommaseparerte URL-er som overvåkes. Tom = standardene over. |
| `MATCH_FILTER` (variable/input) | Varsle bare for kamper som inneholder teksten, f.eks. `Portugal`. |
| `POLL_INTERVAL` / `MAX_MINUTES` | Sekunder mellom sjekker inne i én kjøring, og hvor lenge kjøringen looper. |
| `DUMP_HTML` | `1` skriver ut sideinnholdet i loggen. |

Vil du følge en annen kamp, finn `productId` i URL-en på kampvalgsiden og legg
hele URL-en inn i `RESALE_URLS`.

## Første kjøring: verifiser parseren

Parseren er testet mot markup som tilsvarer det siden viser («Norway vs
Denmark … 0 tickets»), men den er ikke kjørt mot den ekte siden – nettverket i
utviklingsmiljøet har ikke tilgang til `resale.fotball.no`. Kjør derfor
workflowen manuelt én gang med **Dump html** huket av (Actions → Billettvarsler
(fotball) → Run workflow), og se i loggen at kampene og antallene listes ut som
forventet. Ser utskriften annerledes ut, er det `parse_availability()` i
`check_tickets.py` som må justeres – linjene i loggen er nøyaktig det funksjonen
får inn.

## Vær grei mot siden

Sjekk omtrent én gang i minuttet er nok til å rekke en billett, og lite nok til
å ikke belaste siden. Ikke skru frekvensen vesentlig opp – NFFs vilkår gjelder
uansett, og varselet er ment å gi deg beskjed, ikke å kapre billetter automatisk.
