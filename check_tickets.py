#!/usr/bin/env python3
"""Varsler når det dukker opp billetter for videresalg på resale.fotball.no.

Siden er en SecuTix-instans som serverer ferdig rendret HTML: hver kamp vises
som en blokk med kampnavn, dato, arena og et antall ("0 tickets" / "2 billetter").
Vi henter siden, plukker ut antallet per kamp, sammenligner med forrige kjøring
og sender push via ntfy når et antall går fra 0 til noe høyere.

Miljøvariabler:
  NTFY_TOPIC      ntfy-topic det varsles til (samme som vinvarsleren).
  RESALE_URLS     Kommaseparerte URL-er som skal overvåkes. Default: kampvalg-
                  siden for Nations League + den generelle videresalgslista.
  MATCH_FILTER    Valgfritt: varsle bare for kamper som inneholder denne teksten
                  (f.eks. "Portugal"). Tomt = alle kamper.
  POLL_INTERVAL   Sekunder mellom sjekker inne i én kjøring (default 0 = én sjekk).
  MAX_MINUTES     Hvor lenge én kjøring maks skal loope (default 0 = ingen loop).
  DUMP_HTML       "1" for å skrive ut hentet HTML i loggen (feilsøking av parseren).
"""
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL   = "https://ntfy.sh"

DEFAULT_URLS = [
    # Kampvalg for Mens Nations League (Norge–Danmark 24. sep, Norge–Portugal 27. sep)
    "https://resale.fotball.no/selection/event/date"
    "?productId=10229739619905&checkResaleAvailability=true",
    # Generell oversikt over alt som ligger ute for videresalg
    "https://resale.fotball.no/list/resaleProducts/?lang=en",
]

def with_english(url):
    """Legger på lang=en. Uten den svarer siden på serverens språk, og da
    varierer tekstene vi leter etter mellom kjøringer."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(k == "lang" for k, _ in query):
        query.append(("lang", "en"))
    return urllib.parse.urlunsplit(
        parts._replace(query=urllib.parse.urlencode(query))
    )

RESALE_URLS   = [with_english(u.strip())
                 for u in (os.environ.get("RESALE_URLS", "").split(",") or [])
                 if u.strip()] or [with_english(u) for u in DEFAULT_URLS]
MATCH_FILTER  = os.environ.get("MATCH_FILTER", "").strip().lower()
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "0") or 0)
MAX_MINUTES   = int(os.environ.get("MAX_MINUTES", "0") or 0)
DUMP_HTML     = os.environ.get("DUMP_HTML", "") == "1"

STATE_FILE = "data/tickets_state.json"

HOME_URL = "https://resale.fotball.no/"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Fraser som betyr "ingenting ute for salg akkurat nå" – brukes som fallback
# hvis vi ikke klarer å lese ut tall per kamp.
NO_TICKETS_PHRASES = [
    "there are currently no tickets",
    "no tickets are currently",
    "no tickets available",
    "ingen billetter",
    "det er for øyeblikket ingen",
    "no product",
    "ingen produkt",
]

# ─── Henting ──────────────────────────────────────────────────────────────────

# Siden krever en økt-cookie (JSESSIONID) for å svare med ekte innhold – uten
# den serverer den bare «Cookies appear to be disabled». Vi holder derfor på
# cookies gjennom hele kjøringen, akkurat som en vanlig nettleser.
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)

# Sperresider (cookie-vegg, venterom) er nesten tomme – noen få linjer. De ekte
# sidene har over hundre. Ordene «waiting room» og «captcha» finnes også som
# skjulte i18n-strenger i den ekte siden, så antall linjer må avgjøre, ikke
# ordene alene.
BLOCK_PHRASES = [
    "cookies appear to be disabled",
    "waiting room",
    "captcha",
]
MAX_BLOCK_PAGE_LINES = 25

_warmed = False

def fetch_page(url):
    """Henter en side med cookies. Returnerer HTML-tekst, eller None ved feil."""
    global _warmed
    if not _warmed:
        # Hent forsiden én gang først, slik at vi har en gyldig økt før vi ber
        # om billettsiden. Uten dette svarer SecuTix med cookie-advarselen.
        _fetch(HOME_URL)
        _warmed = True
        time.sleep(2)
    return _fetch(url)

def _fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
        "Referer": "https://resale.fotball.no/",
    })
    try:
        with _opener.open(req, timeout=20) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        print(f"    ⚠️  HTTP {e.code} for {url}")
    except Exception as e:
        print(f"    ⚠️  Feil ved henting av {url}: {e}")
    return None

def blocked_by(lines):
    """Returnerer hvilken sperre siden viser (cookie-vegg, venterom, captcha),
    eller None hvis vi faktisk fikk se innhold."""
    if len(lines) > MAX_BLOCK_PAGE_LINES:
        return None
    blob = " ".join(lines).lower()
    for phrase in BLOCK_PHRASES:
        if phrase in blob:
            return phrase
    return None

# ─── Parsing ──────────────────────────────────────────────────────────────────

BLOCK_TAGS = ("div|p|li|tr|td|th|h[1-6]|br|hr|section|article|header|footer|"
              "ul|ol|table|tbody|thead|form|fieldset|button|option|dt|dd|nav|"
              "main|aside|figure|figcaption|blockquote|pre|label")

def html_to_lines(page):
    """Gjør HTML om til en liste med tekstlinjer (én per visuell blokk).

    SecuTix-sidene er server-rendret, så all informasjon vi trenger ligger
    i markupen – vi trenger verken JS-motor eller API-nøkkel. Blokktagger blir
    linjeskift; inline-tagger (span, b, img …) blir mellomrom, slik at en
    kamptittel som «<span>Norway</span> vs <span>Denmark</span>» holdes samlet
    på én linje.
    """
    text = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    text = re.sub(rf"(?i)</?(?:{BLOCK_TAGS})\b[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[\s\u00a0]+", " ", line).strip()
        if line:
            lines.append(line)
    return lines

COUNT_RE   = re.compile(r"^(\d+)\s*(?:tickets?|billetter?)$", re.IGNORECASE)
INLINE_RE  = re.compile(r"(\d+)\s*(?:tickets?|billetter?)\b", re.IGNORECASE)
# «vs» står på egen linje mellom lagnavnene, fordi flaggene ligger imellom
VS_RE      = re.compile(r"^(?:vs\.?|v|mot|[-–])$", re.IGNORECASE)
# Hele kampnavnet på én linje: "Norway vs Denmark"
TITLE_RE   = re.compile(r"^(?!\d)[^\d]{2,60}?\s+(?:vs\.?|mot)\s+[^\d]{2,60}$", re.IGNORECASE)
# "Thursday, 24 September 2026 - 20:45"
DATETIME_RE = re.compile(r"\d{1,2}\s+\w+\s+\d{4}\s*[-–]\s*\d{1,2}[:.]\d{2}")
VENUE_MARKER = re.compile(r"^(?:venue|arena|sted)\s*:?$", re.IGNORECASE)

# Hvor mange linjer over antallet vi leter i etter kampnavn og detaljer.
LOOKBACK = 15

def _title_from(window):
    """Setter sammen kampnavnet fra linjene rett over antallet.

    På den ekte siden ligger lagnavn og «vs» på hver sin linje
    (Norway / vs / Denmark), fordi flaggbildene skiller dem.
    """
    for j in range(len(window) - 2, 0, -1):
        if VS_RE.match(window[j]):
            return f"{window[j - 1]} vs {window[j + 1]}"
    for line in reversed(window):
        if TITLE_RE.match(line):
            return line
    return window[-1] if window else "Ukjent kamp"

def _details_from(window):
    """Plukker ut dato/klokkeslett og arena til bruk i varselteksten."""
    details = []
    for j, line in enumerate(window):
        if DATETIME_RE.search(line):
            details.append(line)
        elif VENUE_MARKER.match(line) and j + 1 < len(window):
            details.append(window[j + 1])
    # behold rekkefølgen, men fjern duplikater
    seen = set()
    return [d for d in details if not (d in seen or seen.add(d))][:3]

def parse_availability(lines):
    """Finner (kamp, detaljer, antall billetter) for hver kamp på siden.

    Antallet står som en egen linje («0 tickets» / «2 billetter»). Alt vi
    trenger for å navngi kampen ligger i linjene rett over.
    """
    entries = []
    for i, line in enumerate(lines):
        m = COUNT_RE.match(line) or (INLINE_RE.search(line) if len(line) <= 40 else None)
        if not m:
            continue
        window = lines[max(0, i - LOOKBACK):i]
        entries.append({
            "title": _title_from(window),
            "details": _details_from(window),
            "count": int(m.group(1)),
        })
    return entries

def page_is_empty(lines):
    """True hvis siden eksplisitt sier at ingenting ligger ute for salg."""
    blob = " ".join(lines).lower()
    return any(p in blob for p in NO_TICKETS_PHRASES)

# ─── Tilstandshåndtering ──────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("events", {})
    state.setdefault("pages", {})
    return state

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ─── Varsling ─────────────────────────────────────────────────────────────────

def send_notification(title, message, priority="high", tags="soccer", click=None):
    if not NTFY_TOPIC:
        print(f"    ⚠️  NTFY_TOPIC ikke satt – hopper over: {title}")
        return
    headers = {"Title": title.encode(), "Priority": priority, "Tags": tags}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"{NTFY_URL}/{NTFY_TOPIC}",
        data=message.encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            print(f"    ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"    ⚠️  Varsel feilet: {e}")

# ─── Sjekk ────────────────────────────────────────────────────────────────────

def event_key(url, entry):
    base = f"{url}|{entry['title']}|{' '.join(entry['details'][:2])}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

def check_url(url, state):
    print(f"    🔍  Sjekker: {url}")
    page = fetch_page(url)
    if page is None:
        return

    lines = html_to_lines(page)
    page_state = state["pages"].setdefault(url, {})

    block = blocked_by(lines)
    if block:
        # Venterom, captcha eller cookie-vegg: vi vet ingenting om billettene.
        # Da varsler vi ikke – verken om billetter eller om «endring».
        print(f"    🚧  Kom ikke gjennom til billettsiden ({block}). "
              "Hopper over uten å varsle.")
        page_state["blocked"] = block
        page_state["blocked_at"] = datetime.now().isoformat()
        if DUMP_HTML:
            for line in lines[:40]:
                print(f"       {line}")
        return
    page_state.pop("blocked", None)

    if DUMP_HTML:
        print(f"    ── sideinnhold ({len(lines)} linjer) ──")
        for line in lines[:200]:
            print(f"       {line}")
        print("    ────────────────────────────────────")

    entries = parse_availability(lines)

    if entries:
        page_state["parse_ok"] = True
        seen_keys = set()
        for entry in entries:
            title = entry["title"]
            key   = event_key(url, entry)
            seen_keys.add(key)
            if MATCH_FILTER and MATCH_FILTER not in title.lower():
                continue

            prev  = state["events"].get(key, {})
            count = entry["count"]
            was   = prev.get("count", 0)
            detail_txt = " · ".join(entry["details"])

            if count > 0 and count > was:
                send_notification(
                    title=f"🎟️ Billetter ute: {title}",
                    message=(
                        f"{title}\n{detail_txt}\n\n"
                        f"{count} billett(er) lagt ut for videresalg.\n"
                        f"Først til mølla – kjøp her:\n{url}"
                    ),
                    priority="urgent",
                    tags="soccer,rotating_light",
                    click=url,
                )
            elif count == 0 and was > 0:
                print(f"    📭  {title}: billettene er borte igjen (var {was}).")
            else:
                print(f"    📭  {title}: {count} billett(er).")

            state["events"][key] = {
                "title": title,
                "details": entry["details"],
                "count": count,
                "url": url,
                "last_checked": datetime.now().isoformat(),
            }

        # Rydd bort kamper vi ikke lenger finner på siden, så tilstandsfila
        # ikke fylles opp av oppføringer som aldri kan bli aktuelle igjen.
        for old_key, old in list(state["events"].items()):
            if old.get("url") == url and old_key not in seen_keys:
                del state["events"][old_key]
        return

    # Ingen tall lot seg lese ut av siden. Da varsler vi KUN på en trygg
    # overgang: siden sa tidligere eksplisitt «ingen billetter», og gjør det
    # ikke lenger. Har vi aldri sett den teksten, vet vi ingenting om
    # tilstanden – da logger vi bare, slik at en parser som ikke treffer
    # ikke kan spamme telefonen med falske varsler.
    empty = page_is_empty(lines)
    was_empty = page_state.get("empty")
    page_state["parse_ok"] = False

    if empty:
        print("    📭  Siden sier at ingen billetter er ute.")
    elif was_empty is True:
        send_notification(
            title="🎟️ Endring på videresalgssiden",
            message=(
                "Teksten «ingen billetter» er borte fra siden – det kan ha "
                f"kommet billetter ut for salg.\n\n{url}"
            ),
            priority="urgent",
            tags="soccer,rotating_light",
            click=url,
        )
    else:
        print("    ⚠️  Fant verken billettall eller «ingen billetter»-tekst – "
              "parseren må tilpasses sidestrukturen (kjør med DUMP_HTML=1). "
              "Varsler ikke, for å unngå falske alarmer.")

    page_state["empty"] = empty

def run_once(state):
    for i, url in enumerate(RESALE_URLS):
        if i:
            time.sleep(5)  # ikke fyr av forespørslene i samme sekund
        check_url(url, state)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Billettvarsler (resale.fotball.no) – "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    if MATCH_FILTER:
        print(f"🎯  Filter: varsler bare for kamper som inneholder '{MATCH_FILTER}'.\n")

    state = load_state()
    state["pages"] = {u: v for u, v in state["pages"].items() if u in RESALE_URLS}
    state["events"] = {k: v for k, v in state["events"].items()
                       if v.get("url") in RESALE_URLS}
    deadline = time.time() + MAX_MINUTES * 60 if MAX_MINUTES else 0

    while True:
        run_once(state)
        save_state(state)
        if not POLL_INTERVAL or not deadline or time.time() + POLL_INTERVAL > deadline:
            break
        print(f"\n⏳  Venter {POLL_INTERVAL}s til neste sjekk...\n")
        time.sleep(POLL_INTERVAL)

    print("\n✅  Ferdig!\n")

if __name__ == "__main__":
    sys.exit(main())
