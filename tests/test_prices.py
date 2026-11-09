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
ITEM = {"navn": "Samsung S90H", "url": "https://x", "malpris": 19990}

alert, st = cp.evaluate(ITEM, 22990, None, 3)
check("første kjøring over målpris: ingen varsel", alert, None)

alert, st2 = cp.evaluate(ITEM, 22490, st, 3)
check("lite fall (2 %): ingen varsel", alert, None)

alert, st3 = cp.evaluate(ITEM, 20990, st2, 3)
check("fall ≥ 3 %: varsel", alert is not None and "Ned" in alert[1], True)
check("… og ny bunn nevnes", "Laveste pris" in alert[1], True)

alert, st4 = cp.evaluate(ITEM, 19490, st3, 3)
check("under målpris: høy prioritet", alert[2], "high")
check("… målpris i teksten", "målprisen" in alert[1], True)

alert, st5 = cp.evaluate(ITEM, 19490, st4, 3)
check("samme pris igjen: ingen gjentatt varsel", alert, None)

alert, st6 = cp.evaluate(ITEM, 19390, st5, 3)
check("faller litt videre under målpris: nytt varsel", alert is not None, True)

alert, st7 = cp.evaluate(ITEM, 21990, st6, 3)
check("prisen stiger: ingen varsel", alert, None)
alert, _ = cp.evaluate(ITEM, 19990, st7, 3)
check("tilbake på målpris etter å ha vært over: varsel igjen", alert is not None, True)

check("laveste huskes", st7["laveste"], 19390)

if failures:
    print("\n❌ Feilet:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("\nAlle tester bestått.")
