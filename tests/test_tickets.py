#!/usr/bin/env python3
"""Tester for billettvarsleren – kjør med: python3 tests/test_tickets.py

Linjesekvensen i REAL_LINES er hentet rett fra en ekte kjøring mot
resale.fotball.no (Actions-loggen med DUMP_HTML=1). Endrer siden struktur,
er det denne som først skal oppdateres.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import check_tickets as ct  # noqa: E402

# Kampvalgsiden slik den faktisk ser ut (lang=en). Lagnavn og «vs» ligger på
# hver sin linje fordi flaggbildene skiller dem.
REAL_LINES = [
    "Performance selection [Mens Nations League] - Norges Fotballforbund",
    "Skip to content", "Mens Nations League", "Ullevaal Stadion",
    "from", "Thursday, 24 September 2026", "to", "Sunday, 27 September 2026",
    "Ullevaal Stadion", "Events", "Team", "Reset", "Any team",
    "Denmark", "Norway", "Portugal",
    "Instruction", "Select one match.", "September 2026",
    "J1", "Day 1", "Date and time:", "Thursday, 24 September 2026 - 20:45",
    "Thu", "24", "Sep", "20:45", "Venue:", "Ullevaal Stadion",
    "Norway", "vs", "Denmark", "0 tickets",
    "J2", "Day 2", "Date and time:", "Sunday, 27 September 2026 - 20:45",
    "Sun", "27", "Sep", "20:45", "Venue:", "Ullevaal Stadion",
    "Norway", "vs", "Portugal", "0 tickets",
    "Events", "Mens Nations League", "Client account", "Log in", "Sign up",
    "Guarantee",
    "The maximal number of tickets for this order has been exceeded.",
    "Unfortunately, the item you have selected is no longer available.",
    "Your cart is empty.",
]

# Videresalgslista når ingenting ligger ute.
EMPTY_LIST_LINES = [
    "Tickets for resale - Norges Fotballforbund", "Skip to content", "INFORMATION",
    "There are currently no tickets being resold. Please visit us again in a few days.",
    "All tickets", "Search", "Filter", "No results were found for this search",
]

# Slik ser en sperreside ut – få linjer, ingen billettinformasjon.
WAITING_ROOM_LINES = ["Waiting Room", "» Button", "New Captcha", "input", "» Submit", "English"]
COOKIE_WALL_LINES = [
    "Cookies appear to be disabled in your browser. - Norges Fotballforbund",
    "Cookies appear to be disabled in your browser.",
    "This site requires browser cookies to function correctly.", "Refresh",
]

failures = []

def check(what, got, want):
    if got != want:
        failures.append(f"{what}\n     fikk:  {got!r}\n     ville: {want!r}")
    else:
        print(f"  ✅  {what}")

def with_counts(dk, pt):
    """REAL_LINES med andre billettall."""
    out, seen = [], 0
    for line in REAL_LINES:
        if line == "0 tickets":
            out.append(f"{[dk, pt][seen]} tickets")
            seen += 1
        else:
            out.append(line)
    return out

def notifications_for(pages):
    """Kjører check_url over en sekvens sider og returnerer varseltitlene."""
    sent = []
    real_send, real_lines, real_fetch = (
        ct.send_notification, ct.html_to_lines, ct.fetch_page)
    ct.send_notification = lambda title, message, priority="high", tags="", click=None: \
        sent.append(title)
    ct.fetch_page = lambda url: "<html/>"
    state = {"events": {}, "pages": {}}
    try:
        for lines in pages:
            ct.html_to_lines = lambda page, lines=lines: lines
            ct.check_url("https://resale.fotball.no/test", state)
    finally:
        ct.send_notification, ct.html_to_lines, ct.fetch_page = (
            real_send, real_lines, real_fetch)
    return sent

print("Parsing av ekte kampvalgside:")
entries = ct.parse_availability(REAL_LINES)
check("finner begge kampene", len(entries), 2)
check("navngir kamp 1", entries[0]["title"], "Norway vs Denmark")
check("navngir kamp 2", entries[1]["title"], "Norway vs Portugal")
check("leser antall", [e["count"] for e in entries], [0, 0])
check("tar med dato og arena", entries[1]["details"],
      ["Sunday, 27 September 2026 - 20:45", "Ullevaal Stadion"])

print("\nKampnavn på én linje (hvis markupen endres):")
check("«Norway vs Portugal» som én linje",
      ct.parse_availability(["Norway vs Portugal", "27 Sep", "3 tickets"])[0]["title"],
      "Norway vs Portugal")
check("norsk variant",
      ct.parse_availability(["Norge", "vs", "Portugal", "2 billetter"])[0]["count"], 2)

print("\nSperresider skal ikke forveksles med innhold:")
check("venterom oppdages", ct.blocked_by(WAITING_ROOM_LINES), "waiting room")
check("cookie-vegg oppdages", ct.blocked_by(COOKIE_WALL_LINES),
      "cookies appear to be disabled")
check("ekte side er ikke sperret", ct.blocked_by(REAL_LINES), None)
check("«ingen billetter» oppdages", ct.page_is_empty(EMPTY_LIST_LINES), True)

print("\nVarsling:")
check("stille når alt er 0", notifications_for([REAL_LINES, REAL_LINES]), [])
check("varsler når billetter dukker opp",
      notifications_for([REAL_LINES, with_counts(0, 2)]),
      ["🎟️ Billetter ute: Norway vs Portugal"])
check("varsler ikke to ganger for samme billetter",
      notifications_for([REAL_LINES, with_counts(0, 2), with_counts(0, 2)]),
      ["🎟️ Billetter ute: Norway vs Portugal"])
check("stille på tom videresalgsliste",
      notifications_for([EMPTY_LIST_LINES, EMPTY_LIST_LINES]), [])
check("stille når vi bare møter sperresider",
      notifications_for([WAITING_ROOM_LINES, COOKIE_WALL_LINES, WAITING_ROOM_LINES]), [])

print("\nTilbaketrekking ved sperre:")

def backoff_scenario():
    """Sperret side skal pauses, hoppes over, og gjenopptas etter pausen."""
    real_lines, real_fetch, real_send = ct.html_to_lines, ct.fetch_page, ct.send_notification
    ct.fetch_page = lambda url: "<html/>"
    ct.send_notification = lambda *a, **k: None
    state = {"events": {}, "pages": {}}
    url = "https://resale.fotball.no/test"
    try:
        ct.html_to_lines = lambda page: WAITING_ROOM_LINES
        ct.check_url(url, state)
        first_pause = state["pages"][url].get("paused_until")

        # Neste kjøring mens pausen løper: siden skal ikke hentes i det hele tatt
        fetched = []
        ct.fetch_page = lambda u: fetched.append(u) or "<html/>"
        ct.check_url(url, state)
        skipped_while_paused = not fetched

        # Etter at pausen er over slipper vi til igjen – og en vellykket sjekk
        # skal nullstille tilbaketrekkingen
        state["pages"][url]["paused_until"] = (
            ct.datetime.now() - ct.timedelta(minutes=1)).isoformat()
        ct.html_to_lines = lambda page: REAL_LINES
        ct.check_url(url, state)
        cleared = "paused_until" not in state["pages"][url] and \
                  "strikes" not in state["pages"][url]
    finally:
        ct.html_to_lines, ct.fetch_page, ct.send_notification = (
            real_lines, real_fetch, real_send)
    return bool(first_pause), skipped_while_paused, cleared

paused, skipped, cleared = backoff_scenario()
check("sperre gir pause", paused, True)
check("henter ikke siden mens pausen løper", skipped, True)
check("vellykket sjekk nullstiller pausen", cleared, True)
check("pausen dobles for hvert forsøk",
      [ct.backoff_until(n)[1] for n in (1, 2, 3, 4, 9)], [10, 20, 40, 60, 60])

if failures:
    print("\n❌  " + f"{len(failures)} test(er) feilet:")
    for f in failures:
        print("   - " + f)
    sys.exit(1)
print("\n✅  Alle tester passerte.")
