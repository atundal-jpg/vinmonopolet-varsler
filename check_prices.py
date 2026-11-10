#!/usr/bin/env python3
"""Prisvarsler for TV-er (og alt annet med en produktside) – laget for Black Friday.

Ønskelista ligger i data/tv_watchlist.json. Hver modell har to prisgrenser
(«god pris» og «knallpris») og én eller flere varianter – Samsung selger samme
TV under flere modellkoder (TQ…, QE…, TU…, UE…), og Prisjakt har én side per
kode. Hver variant har en URL: helst en Prisjakt-produktside, som viser laveste
pris på tvers av butikker, men en produktside hos Elkjøp, Power, Komplett o.l.
fungerer også. Varianter uten URL hoppes over.

Prisen leses fra de strukturerte dataene nettbutikker legger i siden for
Google & co. (schema.org JSON-LD, evt. <meta property="product:price:amount">).
Det er samme data for alle butikker, så vi trenger ingen butikkspesifikk parser.

Hver pris som leses, føres i data/tv_price_log.csv (prishistorikk).

Det varsles via ntfy (samme topic som vin- og billettvarslene) når:
  • prisen kommer innenfor grensene: et ekstra tydelig varsel – 🔥 KNALLPRIS
    (prioritet urgent, lyd og vibrasjon som bryter gjennom) eller ✅ GOD PRIS
    (prioritet high). Én gang per nivå – deretter bare hvis prisen faller
    videre, går opp et nivå, eller har vært over grensen igjen i mellomtiden,
  • prisen ellers faller minst MIN_DROP_PCT prosent siden forrige sjekk: et
    vanlig 📉 prisfall-varsel som viser hvor langt det er igjen til grensene.

Prisjakt oppdaterer selv bare 3–5 ganger i døgnet, så Prisjakt-sider sjekkes
sjeldnere (PRISJAKT_INTERVAL_MIN) enn butikkenes egne sider
(STORE_INTERVAL_MIN). Med MAX_MINUTES > 0 looper én kjøring og sjekker det som
er «forfalt» – slik får vi jevne sjekker selv om GitHub starter planlagte
kjøringer sjeldnere enn vi ber om.

Miljøvariabler:
  NTFY_TOPIC             ntfy-topic det varsles til.
  MIN_DROP_PCT           Minste prisfall (i prosent) som gir varsel. Default 1.
  STORE_INTERVAL_MIN     Minutter mellom sjekk av en butikkside. Default 5.
  PRISJAKT_INTERVAL_MIN  Minutter mellom sjekk av en Prisjakt-side. Default 60.
  MAX_MINUTES            Hvor lenge én kjøring looper. Default 0 = én runde.
  DUMP_HTML              "1" for å skrive starten av hentet HTML i loggen, og
                         utdrag rundt alt som ligner priser (feilsøking).
  URL_FILTER             Feilsøk bare sider der URL-en inneholder denne teksten.
                         Tørrkjøring: lagrer ingenting og sender ingen varsler.
"""
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

NTFY_TOPIC   = os.environ.get("NTFY_TOPIC", "")
NTFY_URL     = "https://ntfy.sh"
MIN_DROP_PCT = float(os.environ.get("MIN_DROP_PCT", "1") or 1)
DUMP_HTML    = os.environ.get("DUMP_HTML", "") == "1"
URL_FILTER   = os.environ.get("URL_FILTER", "").strip().lower()
STORE_INTERVAL_MIN    = float(os.environ.get("STORE_INTERVAL_MIN", "5") or 5)
PRISJAKT_INTERVAL_MIN = float(os.environ.get("PRISJAKT_INTERVAL_MIN", "60") or 60)
MAX_MINUTES           = float(os.environ.get("MAX_MINUTES", "0") or 0)

WATCHLIST_FILE = "data/tv_watchlist.json"
STATE_FILE     = "data/tv_prices_state.json"
LOG_FILE       = "data/tv_price_log.csv"
LOG_HEADER     = ["tidspunkt", "modell", "kode", "butikk", "pris", "niva", "url"]

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Pris under denne andelen av forrige pris regnes som en lesefeil.
SUSPICIOUS_RATIO = 0.4

# Pause mellom forespørsler, så vi er en høflig gjest.
DELAY_SECONDS = 3

# ─── Henting ──────────────────────────────────────────────────────────────────

class Blocked(Exception):
    """Siden ville ikke slippe oss inn (403/429, captcha, bot-sjekk)."""

BLOCK_PHRASES = ["captcha", "are you a robot", "er du en robot",
                 "verify you are human", "access denied", "just a moment"]

def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429, 503):
            raise Blocked(f"HTTP {e.code}")
        raise

def looks_blocked(page):
    """En sperreside er kort og mangler produktdata."""
    if len(page) > 20000 or "application/ld+json" in page:
        return False
    low = page.lower()
    return any(p in low for p in BLOCK_PHRASES)

# ─── Parsing ──────────────────────────────────────────────────────────────────

LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)
META_PRICE_RE = re.compile(
    r'<meta[^>]+(?:property|itemprop|name)=["\'](?:product:price:amount|og:price:amount|price)["\']'
    r'[^>]*content=["\']([^"\']+)["\']', re.IGNORECASE)
META_PRICE_RE_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
    r'(?:property|itemprop|name)=["\'](?:product:price:amount|og:price:amount|price)["\']',
    re.IGNORECASE)

def to_number(value):
    """'22 990,-' / '22990.00' / 22990 → 22990.0. None hvis ikke tolkbar."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = str(value).replace(" ", "").replace(" ", "").replace(",-", "")
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:          # 22.990,00 eller 22,990.00
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:                     # 22990,00 eller 22,990
        head, _, tail = s.rpartition(",")
        s = f"{head}.{tail}" if len(tail) != 3 else head + tail
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")         # 22.990 = tusenskille
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n > 0 else None

def _walk(node):
    """Går gjennom alle objekter i en JSON-LD-struktur (også @graph)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)

def _is_type(obj, name):
    t = obj.get("@type")
    return t == name or (isinstance(t, list) and name in t)

def _offer_prices(offers):
    prices = []
    for o in _walk(offers):
        if not isinstance(o, dict):
            continue
        avail = str(o.get("availability", "")).lower()
        if "outofstock" in avail or "discontinued" in avail:
            continue
        for key in ("lowPrice", "price"):
            n = to_number(o.get(key))
            if n:
                prices.append(n)
        spec = o.get("priceSpecification")
        if isinstance(spec, dict):
            n = to_number(spec.get("price"))
            if n:
                prices.append(n)
    return prices

def extract_price(page):
    """Returnerer (pris, kilde) for sidens hovedprodukt, eller (None, None).

    Bare det første produktet med tilbud brukes: sider kan også ha
    strukturdata for tilbehør og «lignende produkter» lenger ned, og de skal
    ikke kunne gi oss en falsk lavpris.
    """
    for block in LDJSON_RE.findall(page):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        for obj in _walk(data):
            if (_is_type(obj, "Product") or _is_type(obj, "ProductGroup")) and "offers" in obj:
                prices = _offer_prices(obj["offers"])
                if prices:
                    return min(prices), "json-ld"
    for rx in (META_PRICE_RE, META_PRICE_RE_REV):
        metas = [n for n in (to_number(m) for m in rx.findall(page)) if n]
        if metas:
            return min(metas), "meta"
    return None, None

# ─── Tilstand og logg ─────────────────────────────────────────────────────────

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

def append_log(rows, path=LOG_FILE):
    """Legger leste priser til i CSV-loggen (lages med overskrift første gang)."""
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(LOG_HEADER)
        w.writerows(rows)

# ─── Lenker og butikker ───────────────────────────────────────────────────────

STORES = {
    "prisjakt.no": "Prisjakt",
    "elkjop.no": "Elkjøp",
    "power.no": "Power",
    "komplett.no": "Komplett",
    "netonnet.no": "NetOnNet",
    "elon.no": "Elon",
    "samsung.com": "Samsung",
}

# Prismatch-tips i varselet. Ifølge Elkjøp matcher de Komplett, NetOnNet,
# Skousen og Power. Ifølge Tek.no matcher Power bare Elkjøp. Vilkår kan
# endre seg – derfor står det som et tips, ikke en garanti.
PRICE_MATCH_TIPS = {
    "Komplett": "Elkjøp kan matche prisen (prismatch) – ta den med hjem samme dag.",
    "NetOnNet": "Elkjøp kan matche prisen (prismatch) – ta den med hjem samme dag.",
    "Skousen":  "Elkjøp kan matche prisen (prismatch) – ta den med hjem samme dag.",
    "Power":    "Elkjøp kan matche prisen (prismatch).",
    "Elkjøp":   "Power kan matche Elkjøp-prisen (prismatch).",
}

# Sporingsparametre som ikke endrer hvilken vare siden viser.
TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|gclsrc|gbraid|wbraid|fbclid|msclkid|dclid|_ga|_gl|mc_.*|"
    r"ref|referrer|affiliate.*|aff_.*|pj_.*|clickid|cid|srsltid)$", re.IGNORECASE)

def clean_url(url):
    """Fjerner sporingsparametre (utm_*, gclid …) fra en lenke."""
    parts = urllib.parse.urlsplit(url.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not TRACKING_PARAMS.match(k)]
    return urllib.parse.urlunsplit(
        parts._replace(query=urllib.parse.urlencode(query), fragment=""))

def is_prisjakt_redirect(url):
    """Prisjakts «Til butikken»-lenker er klikk som butikkene betaler for.
    De skal aldri polles – bruk adressen du havner på i stedet."""
    parts = urllib.parse.urlsplit(url)
    return parts.netloc.endswith("prisjakt.no") and "product.php" not in parts.path \
        and not parts.path.startswith("/product")

def store_name(variant):
    if variant.get("butikk"):
        return variant["butikk"]
    host = urllib.parse.urlsplit(variant["url"]).netloc.lower()
    for domain, name in STORES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host.removeprefix("www.")

def interval_for(variant):
    return PRISJAKT_INTERVAL_MIN if store_name(variant) == "Prisjakt" else STORE_INTERVAL_MIN

def variants(watchlist):
    """Flater ut ønskelista til (modell, variant)-par med ryddet URL.
    Hopper over tomme URL-er og Prisjakt-viderekoblinger."""
    for model in watchlist:
        for v in model.get("varianter", []):
            raw = v.get("url", "").strip()
            if not raw:
                continue
            if is_prisjakt_redirect(raw):
                print(f"⛔ {model['modell']}: {raw} er en Prisjakt-viderekobling "
                      "(betalt klikk) – bruk butikkens egen adresse. Hoppes over.")
                continue
            yield model, {**v, "url": clean_url(raw)}

def is_due(state_entry, interval_min, now):
    """Er det på tide å sjekke denne siden igjen?"""
    last = (state_entry or {}).get("sist_sjekket")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    # Litt slingringsmonn, så en sjekk som kom noen sekunder for tidlig ikke
    # skyver neste sjekk et helt intervall ut.
    return now - last_dt >= timedelta(minutes=interval_min) - timedelta(seconds=30)

# ─── Beslutning ───────────────────────────────────────────────────────────────

LEVELS = {None: 0, "god": 1, "knall": 2}
LEVEL_TITLE    = {"god": "✅ GOD PRIS", "knall": "🔥 KNALLPRIS"}
LEVEL_PRIORITY = {"god": "high", "knall": "urgent"}
LEVEL_TAGS     = {"god": "white_check_mark,tv", "knall": "rotating_light,fire,tv"}
DROP_TAGS      = "chart_with_downwards_trend,tv"

def kr(n):
    return f"{int(round(n)):,}".replace(",", " ") + " kr"

def level_for(model, price):
    knall = to_number(model.get("knallpris"))
    god   = to_number(model.get("god_pris"))
    if knall and price <= knall:
        return "knall"
    if god and price <= god:
        return "god"
    return None

def evaluate(model, variant, price, prev, min_drop_pct=MIN_DROP_PCT):
    """Avgjør om det skal varsles. Ren funksjon, så den kan testes.

    Returnerer (varsel eller None, ny tilstand). Varselet er en dict med
    tittel, tekst, prioritet, tags og type («knall», «god» eller «fall»).
    """
    prev   = prev or {}
    last   = prev.get("pris")
    lowest = prev.get("laveste")
    level  = level_for(model, price)
    notified_level = prev.get("varslet_niva")
    notified_price = prev.get("varslet_pris")
    god   = to_number(model.get("god_pris"))
    knall = to_number(model.get("knallpris"))

    new = {
        "modell": model["modell"],
        "kode": variant.get("kode", ""),
        "butikk": store_name(variant),
        "pris": price,
        "laveste": min(price, lowest) if lowest else price,
        "niva": level,
        "varslet_niva": notified_level,
        "varslet_pris": notified_price,
    }

    level_hit = False
    if level:
        if (LEVELS[level] > LEVELS[notified_level]
                or notified_price is None or price < notified_price):
            level_hit = True
            new["varslet_niva"] = level
            new["varslet_pris"] = price
    else:
        # Over grensene igjen: klar til å varsle på nytt neste gang.
        new["varslet_niva"] = None
        new["varslet_pris"] = None

    drop_line = None
    if last and price < last:
        drop_pct = (last - price) / last * 100
        if drop_pct >= min_drop_pct:
            drop_line = f"📉 Ned {kr(last - price)} ({drop_pct:.0f} %) fra {kr(last)}"

    if not level_hit and not drop_line:
        return None, new

    code = variant.get("kode")
    shop = store_name(variant)
    what = f"{model['modell']}: {kr(price)} hos {shop}"
    lines = []

    if level_hit:
        # Det tydelige varselet: grensen står først, både i tittel og tekst.
        limit = knall if level == "knall" else god
        title = f"{LEVEL_TITLE[level]} – {what}"
        lines.append(f"{LEVEL_TITLE[level]}! Innenfor grensen din på {kr(limit)}"
                     + (f" ({kr(limit - price)} under)." if price < limit else "."))
        priority, tags, kind = LEVEL_PRIORITY[level], LEVEL_TAGS[level], level
    else:
        title = f"📉 Prisfall – {what}"
        # Hvor langt er det igjen? Gir mening å vite ved et vanlig prisfall.
        if knall and price > knall and level == "god":
            lines.append(f"Innenfor god pris – {kr(price - knall)} igjen til knallpris.")
        elif god and price > god:
            lines.append(f"{kr(price - god)} igjen til god pris ({kr(god)}).")
        priority, tags, kind = "default", DROP_TAGS, "fall"

    if drop_line:
        lines.append(drop_line)
    if lowest and price < lowest:
        lines.append(f"🏆 Laveste pris vi har sett (forrige bunn: {kr(lowest)})")
    if code:
        lines.append(f"Modell: {code}")
    lines.append("")
    if god:
        lines.append(f"God pris: ≤ {kr(god)}")
    if knall:
        lines.append(f"Knallpris: ≤ {kr(knall)}")
    tip = PRICE_MATCH_TIPS.get(shop)
    if tip and level_hit:
        lines.append(f"💡 {tip} Sjekk vilkårene.")
    lines.append(variant["url"])
    return {"tittel": title, "tekst": "\n".join(lines), "prioritet": priority,
            "tags": tags, "type": kind, "butikk": shop}, new

# ─── Varsling ─────────────────────────────────────────────────────────────────

def send_notification(title, message, priority="default", click=None,
                      tags="tv,moneybag", shop=None):
    if not NTFY_TOPIC:
        print(f"    ⚠️  NTFY_TOPIC ikke satt – hopper over: {title}")
        return
    headers = {"Title": title.encode(), "Priority": priority, "Tags": tags}
    if click:
        headers["Click"] = click
        # Knapp rett til butikken i varselet (ntfy skiller felt med komma).
        if "," not in click:
            headers["Actions"] = f"view, Åpne hos {shop or 'butikken'}, {click}".encode()
    req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}",
                                 data=message.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            print(f"    ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"    ⚠️  Varsel feilet: {e}")

# ─── Feilsøking ───────────────────────────────────────────────────────────────

PRICE_HINT_RE = re.compile(r"(?i)price|pris|amount|\bkr\b|nok")

def dump_page(page, max_hints=40):
    """Skriver ut det vi trenger for å lære en ny sidestruktur: starten av
    siden, alle <script>-blokker med type/id/størrelse, og korte utdrag rundt
    ord som ligner priser."""
    print(f"    ── {len(page)} tegn ──")
    print(page[:1500])
    print("    ── script-blokker ──")
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", page, re.I | re.S):
        attrs = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
        body = m.group(2).strip()
        if body:
            start = re.sub(r"\s+", " ", body[:100])
            print(f"    <script {attrs}> {len(body)} tegn: {start}")
    print("    ── prisutdrag ──")
    seen = set()
    for m in PRICE_HINT_RE.finditer(page):
        a, b = max(0, m.start() - 90), min(len(page), m.end() + 90)
        snippet = re.sub(r"\s+", " ", page[a:b])
        key = snippet[60:140]
        if key in seen:
            continue
        seen.add(key)
        print(f"    …{snippet}…")
        if len(seen) >= max_hints:
            break

# ─── Hovedløp ─────────────────────────────────────────────────────────────────

def check_one(model, variant, state, log_rows, now):
    """Henter én side og varsler ved behov. Returnerer True hvis vi leste en pris."""
    url = variant["url"]
    shop = store_name(variant)
    label = f"{model['modell']} – {variant.get('kode', '')} hos {shop}"
    stamp = now.isoformat(timespec="seconds")
    # Registrer forsøket uansett utfall, så en side som feiler ikke prøves
    # på nytt hvert sekund.
    entry = state.setdefault(url, {})
    entry["sist_sjekket"] = stamp
    try:
        page = fetch_page(url)
    except Blocked as e:
        # Sperren respekteres – vi prøver ikke å omgå den, og varsler ikke
        # på noe vi ikke vet.
        print(f"🚧 {label}: kom ikke inn ({e}).")
        return False
    except Exception as e:
        print(f"⚠️  {label}: feil ved henting: {e}")
        return False

    if DUMP_HTML:
        dump_page(page)
    if looks_blocked(page):
        print(f"🚧 {label}: fikk en sperreside (captcha/bot-sjekk).")
        return False

    price, source = extract_price(page)
    if price is None:
        print(f"❓ {label}: fant ingen pris på siden.")
        return False

    prev = entry if entry.get("pris") else None
    if prev and price < prev["pris"] * SUSPICIOUS_RATIO:
        # Et fall på over 60 % er nesten alltid feil vare/feil tall, ikke
        # Black Friday. Behold forrige tilstand og ikke logg tallet.
        print(f"🤨 {label}: {kr(price)} er mistenkelig lavt mot {kr(prev['pris'])} – ignoreres.")
        return True
    print(f"💰 {label}: {kr(price)} ({source})"
          + (f" – forrige: {kr(prev['pris'])}" if prev else ""))
    alert, new = evaluate(model, variant, price, prev)
    new["sist_sjekket"] = stamp
    state[url] = new
    log_rows.append([stamp, model["modell"], variant.get("kode", ""), shop,
                     int(round(price)), new["niva"] or "", url])
    if alert:
        if URL_FILTER:
            print(f"    🔧 Ville varslet: {alert['tittel']}")
            return True
        send_notification(alert["tittel"], alert["tekst"], alert["prioritet"],
                          click=url, tags=alert["tags"], shop=alert["butikk"])
    return True

def main():
    watchlist = load_json(WATCHLIST_FILE, [])
    for model in watchlist:
        missing = [v.get("kode", "?") for v in model.get("varianter", [])
                   if not v.get("url", "").strip()]
        if missing:
            print(f"ℹ️  {model['modell']}: mangler URL for {', '.join(missing)} – hoppes over.")
    todo = list(variants(watchlist))
    if URL_FILTER:
        todo = [(m, v) for m, v in todo if URL_FILTER in v["url"].lower()]
        print(f"🔧 Feilsøking: bare sider med «{URL_FILTER}» ({len(todo)} stk). "
              "Ingenting lagres, ingen varsler sendes.")
    if not todo:
        print(f"Ingen varer med URL i {WATCHLIST_FILE}.")
        return 0

    stores = sorted({store_name(v) for _, v in todo})
    print(f"Følger {len(todo)} sider hos {', '.join(stores)}. "
          f"Butikker hvert {STORE_INTERVAL_MIN:g}. min, Prisjakt hvert {PRISJAKT_INTERVAL_MIN:g}. min.")

    state = load_json(STATE_FILE, {})
    started = datetime.now(timezone.utc)
    deadline = started + timedelta(minutes=MAX_MINUTES)
    tried = read_ok = 0
    log_rows = []

    while True:
        now = datetime.now(timezone.utc)
        due = [(m, v) for m, v in todo if is_due(state.get(v["url"]), interval_for(v), now)]
        if due:
            print(f"\n── Runde {now.strftime('%H:%M')} UTC: {len(due)} sider ──")
        for k, (model, variant) in enumerate(due):
            if k:
                time.sleep(DELAY_SECONDS)
            tried += 1
            read_ok += check_one(model, variant, state, log_rows,
                                 datetime.now(timezone.utc))
        # Lagre etter hver runde, så et avbrudd ikke koster historikk.
        if not URL_FILTER:
            save_state(state)
            append_log(log_rows)
        log_rows = []

        if MAX_MINUTES <= 0:
            break
        # Sov til neste side forfaller, men ikke forbi fristen.
        now = datetime.now(timezone.utc)
        waits = []
        for _, v in todo:
            last = state.get(v["url"], {}).get("sist_sjekket")
            nxt = (datetime.fromisoformat(last) + timedelta(minutes=interval_for(v))
                   if last else now)
            waits.append((nxt - now).total_seconds())
        sleep_s = max(5, min(waits))
        if now + timedelta(seconds=sleep_s) >= deadline:
            break
        time.sleep(sleep_s)

    # Fjern tilstand for sider som er tatt ut av ønskelista.
    urls = {v["url"] for _, v in todo}
    for url in [u for u in state if u not in urls]:
        del state[url]
    if not URL_FILTER:
        save_state(state)

    print(f"\nLeste pris i {read_ok} av {tried} forsøk.")
    # Klarer vi ikke lese en eneste pris, er noe galt – feil kjøringen så
    # workflowen sender et «varsleren feilet»-varsel i stedet for å tie.
    return 0 if read_ok or not tried else 1

if __name__ == "__main__":
    sys.exit(main())
