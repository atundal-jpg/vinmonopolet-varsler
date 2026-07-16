#!/usr/bin/env python3
"""Engangs-diagnoseskript: finner Vinmonopolets FAKTISKE brand-nøkkel for en
produsent. Slettes etter bruk."""
import json
import urllib.parse
import urllib.request

def search(query, page_size=20):
    params = urllib.parse.urlencode({
        "fields": "FULL",
        "pageSize": page_size,
        "currentPage": 0,
        "q": query,
    })
    url = f"https://www.vinmonopolet.no/vmpws/v2/vmp/products/search?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
        "Referer": "https://www.vinmonopolet.no/",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def try_query(label, query):
    data = search(query)
    n = len(data.get("products", []))
    print(f"\n--- {label} ---\nquery={query!r}\nAntall produkter: {n}")
    for p in data.get("products", []):
        print(f"  code={p.get('code')!r}  name={p.get('name')!r}")
    return data

def main():
    # 1) Full rådump av ett produkt fra et fritekstsøk, for å se ALLE felter.
    data = try_query("Fritekstsøk", "Elise Bougy:relevance")
    prods = data.get("products", [])
    if prods:
        print("\n=== FULL rådump av første produkt (json) ===")
        print(json.dumps(prods[0], ensure_ascii=False, indent=2))
        print("\n=== url-felt for begge produkter ===")
        for p in prods:
            print(f"  {p.get('code')}: {p.get('url')!r}")

    # 2) Bekreft at dagens gjettede brand-nøkkel gir 0 treff.
    try_query("Brand-filter (gjettet nøkkel)", ":name-asc:brand:elise_bougy")

    # 3) Prøv noen alternative varianter av brand-nøkkelen.
    candidates = [
        "elisebougy",
        "bougy",
        "elise-bougy",
        "elise_bougy_champagne",
        "champagne_elise_bougy",
        "e_bougy",
    ]
    for c in candidates:
        try_query(f"Brand-filter (variant: {c})", f":name-asc:brand:{c}")

    # 4) Sjekk en produsent vi VET fungerer, som fasit på hvordan et
    #    riktig brand-svar med treff faktisk ser ut (fasetter osv).
    data_ok = try_query("Kontroll: kjent fungerende produsent (Dom. Raveneau)",
                         ":name-asc:brand:dom_raveneau:mainCategory:hvitvin")
    print("\n=== Fasetter for KONTROLL-søket (leter etter brand) ===")
    for facet in data_ok.get("facets", []):
        code = facet.get("code", "")
        name = facet.get("name", "")
        values = facet.get("values", [])
        interesting = "brand" in code.lower() or "produsent" in name.lower() or "brand" in name.lower()
        marker = " <-- SER RELEVANT UT" if interesting else ""
        print(f"  facet code={code!r} name={name!r} ({len(values)} verdier){marker}")
        if interesting:
            for v in values[:10]:
                print(f"      code={v.get('code')!r}  name={v.get('name')!r}  count={v.get('count')}")

if __name__ == "__main__":
    main()
