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
  • prisen når «knallpris» (prioritet urgent) eller «god pris» (prioritet high).
    Én gang per nivå – deretter bare hvis prisen faller videre, går opp et
    nivå, eller har vært over grensen igjen i mellomtiden,
  • prisen faller minst MIN_DROP_PCT prosent siden forrige kjøring.

Miljøvariabler:
  NTFY_TOPIC     ntfy-topic det varsles til.
  MIN_DROP_PCT   Minste prisfall (i prosent) som gir varsel. Default 3.
  DUMP_HTML      "1" for å skrive starten av hentet HTML i loggen (feilsøking).
"""
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

NTFY_TOPIC   = os.environ.get("NTFY_TOPIC", "")
NTFY_URL     = "https://ntfy.sh"
MIN_DROP_PCT = float(os.environ.get("MIN_DROP_PCT", "3") or 3)
DUMP_HTML    = os.environ.get("DUMP_HTML", "") == "1"

WATCHLIST_FILE = "data/tv_watchlist.json"
STATE_FILE     = "data/tv_prices_state.json"
LOG_FILE       = "data/tv_price_log.csv"
LOG_HEADER     = ["tidspunkt", "modell", "kode", "pris", "niva", "url"]

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

def variants(watchlist):
    """Flater ut ønskelista til (modell, variant)-par. Hopper over tomme URL-er."""
    for model in watchlist:
        for v in model.get("varianter", []):
            if v.get("url", "").strip():
                yield model, v

# ─── Beslutning ───────────────────────────────────────────────────────────────

LEVELS = {None: 0, "god": 1, "knall": 2}
LEVEL_TEXT = {"god": "✅ God pris", "knall": "🔥 KNALLPRIS"}
LEVEL_PRIORITY = {"god": "high", "knall": "urgent"}

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

    Returnerer (varsel eller None, ny tilstand). Varselet er (tittel, tekst,
    prioritet).
    """
    prev   = prev or {}
    last   = prev.get("pris")
    lowest = prev.get("laveste")
    level  = level_for(model, price)
    notified_level = prev.get("varslet_niva")
    notified_price = prev.get("varslet_pris")

    new = {
        "modell": model["modell"],
        "kode": variant.get("kode", ""),
        "pris": price,
        "laveste": min(price, lowest) if lowest else price,
        "niva": level,
        "varslet_niva": notified_level,
        "varslet_pris": notified_price,
    }

    reasons = []
    priority = "default"

    if level:
        if (LEVELS[level] > LEVELS[notified_level]
                or notified_price is None or price < notified_price):
            reasons.append(f"{LEVEL_TEXT[level]}!")
            priority = LEVEL_PRIORITY[level]
            new["varslet_niva"] = level
            new["varslet_pris"] = price
    else:
        # Over grensene igjen: klar til å varsle på nytt neste gang.
        new["varslet_niva"] = None
        new["varslet_pris"] = None

    if last and price < last:
        drop_pct = (last - price) / last * 100
        if drop_pct >= min_drop_pct:
            reasons.append(f"📉 Ned {kr(last - price)} ({drop_pct:.0f} %) fra {kr(last)}")
            if lowest and price < lowest:
                reasons.append(f"🏆 Laveste pris vi har sett (forrige bunn: {kr(lowest)})")

    if not reasons:
        return None, new

    code = variant.get("kode")
    title = f"{model['modell']}: {kr(price)}" + (f" ({code})" if code else "")
    lines = reasons + [""]
    if model.get("god_pris"):
        lines.append(f"God pris: ≤ {kr(to_number(model['god_pris']))}")
    if model.get("knallpris"):
        lines.append(f"Knallpris: ≤ {kr(to_number(model['knallpris']))}")
    lines.append(variant["url"])
    return (title, "\n".join(lines), priority), new

# ─── Varsling ─────────────────────────────────────────────────────────────────

def send_notification(title, message, priority="default", click=None):
    if not NTFY_TOPIC:
        print(f"    ⚠️  NTFY_TOPIC ikke satt – hopper over: {title}")
        return
    headers = {"Title": title.encode(), "Priority": priority, "Tags": "tv,moneybag"}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}",
                                 data=message.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            print(f"    ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"    ⚠️  Varsel feilet: {e}")

# ─── Hovedløp ─────────────────────────────────────────────────────────────────

def main():
    watchlist = load_json(WATCHLIST_FILE, [])
    for model in watchlist:
        missing = [v.get("kode", "?") for v in model.get("varianter", [])
                   if not v.get("url", "").strip()]
        if missing:
            print(f"ℹ️  {model['modell']}: mangler URL for {', '.join(missing)} – hoppes over.")
    todo = list(variants(watchlist))
    if not todo:
        print(f"Ingen varer med URL i {WATCHLIST_FILE}.")
        return 0

    state = load_json(STATE_FILE, {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_rows = []
    read_ok = 0

    for i, (model, variant) in enumerate(todo):
        url = variant["url"].strip()
        print(f"🔎 {model['modell']} – {variant.get('kode', url)}")
        if i:
            time.sleep(DELAY_SECONDS)
        try:
            page = fetch_page(url)
        except Blocked as e:
            # Sperren respekteres – vi prøver ikke å omgå den, og varsler ikke
            # på noe vi ikke vet.
            print(f"    🚧 Kom ikke inn ({e}). Hopper over.")
            continue
        except Exception as e:
            print(f"    ⚠️  Feil ved henting: {e}")
            continue

        if DUMP_HTML:
            print(page[:3000])
        if looks_blocked(page):
            print("    🚧 Fikk en sperreside (captcha/bot-sjekk). Hopper over.")
            continue

        price, source = extract_price(page)
        if price is None:
            print("    ❓ Fant ingen pris på siden – ingen varsel.")
            continue

        read_ok += 1
        prev = state.get(url)
        if prev and prev.get("pris") and price < prev["pris"] * SUSPICIOUS_RATIO:
            # Et fall på over 60 % er nesten alltid feil vare/feil tall, ikke
            # Black Friday. Behold forrige tilstand og ikke logg tallet.
            print(f"    🤨 {kr(price)} er mistenkelig lavt mot {kr(prev['pris'])} – ignoreres.")
            continue
        print(f"    💰 {kr(price)} ({source})"
              + (f" – forrige: {kr(prev['pris'])}" if prev and prev.get("pris") else ""))
        alert, new = evaluate(model, variant, price, prev)
        new["sist_sjekket"] = now
        state[url] = new
        log_rows.append([now, model["modell"], variant.get("kode", ""),
                         int(round(price)), new["niva"] or "", url])
        if alert:
            title, message, priority = alert
            send_notification(title, message, priority, click=url)

    # Fjern tilstand for varer som er tatt ut av ønskelista.
    urls = {v["url"].strip() for _, v in todo}
    for url in [u for u in state if u not in urls]:
        del state[url]

    save_state(state)
    append_log(log_rows)
    print(f"\nLeste pris for {read_ok} av {len(todo)} varianter.")
    # Klarer vi ikke lese en eneste pris, er noe galt – feil kjøringen så
    # workflowen sender et «varsleren feilet»-varsel i stedet for å tie.
    return 0 if read_ok else 1

if __name__ == "__main__":
    sys.exit(main())
