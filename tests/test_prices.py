#!/usr/bin/env python3
"""Tester for TV-prisvarsleren – kjør med: python3 tests/test_prices.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import check_prices as cp  # noqa: E402

failures = []

def check(what, got, want):
    if got != want:
        failures.append(f"{what}\n     fikk:  {got!r}\n     ville: {want!r}")
    else:
        print(f"  ✅  {what}")

# ─── Tall ─────────────────────────────────────────────────────────────────────
check("heltall", cp.to_number(22990), 22990.0)
check("mellomrom og ,-", cp.to_number("22 990,-"), 22990.0)
check("hardt mellomrom", cp.to_number("22 990 kr"), 22990.0)
check("desimalpunktum", cp.to_number("22990.00"), 22990.0)
check("desimalkomma", cp.to_number("22990,50"), 22990.5)
check("punktum som tusenskille", cp.to_number("22.990"), 22990.0)
check("europeisk format", cp.to_number("22.990,00"), 22990.0)
check("tomt", cp.to_number(""), None)
check("null", cp.to_number("0"), None)

# ─── Prisuttrekk ──────────────────────────────────────────────────────────────
PRISJAKT_LIKE = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
 "name":"Samsung S90H 65","offers":{"@type":"AggregateOffer","priceCurrency":"NOK",
 "lowPrice":"22990","highPrice":"29990","offerCount":9}}</script></head></html>"""
check("Prisjakt AggregateOffer", cp.extract_price(PRISJAKT_LIKE), (22990.0, "json-ld"))

STORE_LIKE = """<script type="application/ld+json">{"@context":"https://schema.org",
"@graph":[{"@type":"BreadcrumbList"},{"@type":["Product"],"name":"TV",
"offers":[{"@type":"Offer","price":24990,"availability":"https://schema.org/InStock"},
{"@type":"Offer","price":19990,"availability":"https://schema.org/OutOfStock"}]}]}</script>"""
check("butikk med @graph, utsolgt tilbud ignoreres", cp.extract_price(STORE_LIKE),
      (24990.0, "json-ld"))

WITH_ACCESSORY = PRISJAKT_LIKE + """<script type="application/ld+json">{"@type":"Product",
"name":"Veggfeste","offers":{"@type":"Offer","price":605}}</script>"""
check("tilbehør lenger ned ignoreres", cp.extract_price(WITH_ACCESSORY), (22990.0, "json-ld"))

META_ONLY = '<meta property="product:price:amount" content="21 490,00">'
check("meta-fallback", cp.extract_price(META_ONLY), (21490.0, "meta"))
check("ingen pris", cp.extract_price("<html>hei</html>"), (None, None))
check("ødelagt JSON-LD", cp.extract_price(
    '<script type="application/ld+json">{oops</script>'), (None, None))

check("captcha-side er sperret", cp.looks_blocked("<html>Please solve the CAPTCHA</html>"), True)
check("produktside er ikke sperret", cp.looks_blocked(PRISJAKT_LIKE + "captcha"), False)

# ─── Varslingslogikk ──────────────────────────────────────────────────────────
MODEL = {"modell": "QN70F 75\"", "god_pris": 10990, "knallpris": 9990}
VAR = {"kode": "QE75QN70F", "url": "https://www.elkjop.no/product/tv/123"}

def ev(price, prev):
    return cp.evaluate(MODEL, VAR, price, prev, 1)

check("nivå over grensene", cp.level_for(MODEL, 11000), None)
check("nivå god pris (på grensen)", cp.level_for(MODEL, 10990), "god")
check("nivå knallpris (på grensen)", cp.level_for(MODEL, 9990), "knall")

alert, st = ev(12176, None)
check("første kjøring over grensene: ingen varsel", alert, None)

alert, st1 = ev(12100, st)
check("lite fall (0,6 %): ingen varsel", alert, None)

alert, st2 = ev(11490, st1)
check("prisfall over grensene: vanlig varsel", alert["type"], "fall")
check("… normal prioritet", alert["prioritet"], "default")
check("… tittel", alert["tittel"], "📉 Prisfall – QN70F 75\": 11 490 kr hos Elkjøp")
check("… viser hva som gjenstår", "500 kr igjen til god pris" in alert["tekst"], True)
check("… ingen prismatch-tips på vanlig fall", "prismatch" in alert["tekst"], False)

alert, st3 = ev(10990, st2)
check("god pris: tydelig varsel", alert["type"], "god")
check("… prioritet high", alert["prioritet"], "high")
check("… tittel starter med GOD PRIS", alert["tittel"],
      "✅ GOD PRIS – QN70F 75\": 10 990 kr hos Elkjøp")
check("… første linje sier det", alert["tekst"].splitlines()[0],
      "✅ GOD PRIS! Innenfor grensen din på 10 990 kr.")
check("… nevner fallet og modellkoden",
      "Ned 500 kr" in alert["tekst"] and "QE75QN70F" in alert["tekst"], True)
check("… prismatch-tips for Elkjøp", "Power kan matche" in alert["tekst"], True)

alert, st4 = ev(10990, st3)
check("samme pris igjen: ingen gjentatt varsel", alert, None)

alert, st5 = ev(9990, st4)
check("knallpris: prioritet urgent", alert["prioritet"], "urgent")
check("… tittel starter med KNALLPRIS", alert["tittel"].startswith("🔥 KNALLPRIS – "), True)
check("… egne tags", alert["tags"], "rotating_light,fire,tv")

alert, st6 = ev(9790, st5)
check("faller videre innenfor knallpris: nytt knallvarsel", alert["type"], "knall")
check("… sier hvor langt under grensen", "(200 kr under)" in alert["tekst"], True)

alert, st7 = ev(10490, st6)
check("stiger fra knall til god: ingen varsel", alert, None)

alert, st7b = ev(10290, st7)
check("faller innenfor god pris etter å ha vært knall: vanlig fall-varsel",
      alert["type"], "fall")
check("… viser avstand til knallpris", "300 kr igjen til knallpris" in alert["tekst"], True)

alert, st8 = ev(11990, st7b)
check("over grensene igjen: ingen varsel", alert, None)
alert, _ = ev(10990, st8)
check("tilbake på god pris etter å ha vært over: varsel igjen", alert is not None, True)

check("laveste huskes", st8["laveste"], 9790)
check("nivå lagres i tilstanden", st5["niva"], "knall")

# ─── Ønskeliste og logg ───────────────────────────────────────────────────────
import json, tempfile  # noqa: E401,E402
WL = [{"modell": "A", "varianter": [{"kode": "a1", "url": "u1"}, {"kode": "a2", "url": ""}]},
      {"modell": "B", "varianter": [{"kode": "b1", "url": " u2 "}]}]
check("varianter uten URL hoppes over",
      [v["kode"] for _, v in cp.variants(WL)], ["a1", "b1"])

real = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "tv_watchlist.json")))
check("ønskelista har gyldige grenser",
      all(m["knallpris"] < m["god_pris"] for m in real), True)

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "log.csv")
    cp.append_log([["t1", "A", "a1", "Power", 10990, "god", "u1"]], path)
    cp.append_log([["t2", "A", "a1", "Power", 9990, "knall", "u1"]], path)
    rows = open(path, encoding="utf-8").read().splitlines()
    check("logg: overskrift én gang + to rader", rows,
          ["tidspunkt,modell,kode,butikk,pris,niva,url",
           "t1,A,a1,Power,10990,god,u1", "t2,A,a1,Power,9990,knall,u1"])

# ─── Lenker, butikker og intervaller ──────────────────────────────────────────
from datetime import datetime, timedelta, timezone  # noqa: E402
check("sporingsparametre fjernes",
      cp.clean_url("https://www.power.no/tv/p-123/?utm_source=prisjakt&gclid=x&color=sort#anm"),
      "https://www.power.no/tv/p-123/?color=sort")
check("Google-sporing (_gl, gbraid) fjernes",
      cp.clean_url("https://www.elon.no/samsung-75-tu75m80hauxxc-154672?_gl=1*abc&gclid=x&gbraid=y"),
      "https://www.elon.no/samsung-75-tu75m80hauxxc-154672")
check("Prisjakt-produktside er ikke viderekobling",
      cp.is_prisjakt_redirect("https://www.prisjakt.no/product.php?p=14816418"), False)
check("Prisjakt «til butikken» er viderekobling",
      cp.is_prisjakt_redirect("https://www.prisjakt.no/go-to-shop/1234/offer/5678"), True)
check("butikk fra domene: Elon", cp.store_name({"url": "https://www.elon.no/x"}), "Elon")
check("butikk fra domene: NetOnNet", cp.store_name({"url": "https://www.netonnet.no/art/x"}), "NetOnNet")
check("butikk fra domene: Samsung", cp.store_name({"url": "https://www.samsung.com/no/tvs/x"}), "Samsung")
alert, _ = cp.evaluate(MODEL, {"kode": "k", "url": "https://www.komplett.no/product/1"}, 9990, None, 3)
check("prismatch-tips for Komplett", "Elkjøp kan matche" in alert["tekst"], True)
check("butikk kan overstyres", cp.store_name({"url": "https://x.no", "butikk": "X"}), "X")
check("Prisjakt sjekkes sjeldnere",
      cp.interval_for({"url": "https://www.prisjakt.no/product.php?p=1"}) > cp.interval_for(
          {"url": "https://www.komplett.no/product/1"}), True)
now = datetime(2026, 11, 27, 6, 0, tzinfo=timezone.utc)
ago = lambda m: {"sist_sjekket": (now - timedelta(minutes=m)).isoformat()}  # noqa: E731
check("aldri sjekket: forfalt", cp.is_due(None, 5, now), True)
check("sjekket for 2 min siden: ikke forfalt", cp.is_due(ago(2), 5, now), False)
check("sjekket for 4 min 45 s siden: forfalt (slingringsmonn)", cp.is_due(ago(4.75), 5, now), True)
check("Prisjakt sjekket for 30 min siden: ikke forfalt", cp.is_due(ago(30), 60, now), False)
WL2 = [{"modell": "A", "varianter": [
    {"kode": "a", "url": "https://www.prisjakt.no/go-to-shop/1/offer/2"},
    {"kode": "a", "url": "https://www.elkjop.no/p/1?utm_medium=cpc"}]}]
check("viderekoblinger hoppes over, sporing fjernes",
      [v["url"] for _, v in cp.variants(WL2)], ["https://www.elkjop.no/p/1"])

if failures:
    print("\n❌ Feilet:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("\nAlle tester bestått.")
