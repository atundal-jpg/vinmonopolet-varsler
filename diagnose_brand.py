#!/usr/bin/env python3
"""Engangs-diagnoseskript: finner Vinmonopolets FAKTISKE brand-nøkkel for en
produsent, ved å søke fritekst og se hva 'brand'-fasetten i svaret faktisk
inneholder. Brukes til å feilsøke producer_to_brand_key()-gjetningen i
check_products.py. Slettes etter bruk."""
import json
import urllib.parse
import urllib.request

PRODUCER = "Elise Bougy"

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

def main():
    print(f"=== Fritekstsøk: '{PRODUCER}:relevance' ===")
    data = search(f"{PRODUCER}:relevance")
    print(f"Antall produkter: {len(data.get('products', []))}")
    for p in data.get("products", []):
        print(f"  code={p.get('code')!r}  name={p.get('name')!r}")

    print("\n=== Fasetter i svaret (leter etter brand-relatert) ===")
    for facet in data.get("facets", []):
        code = facet.get("code", "")
        name = facet.get("name", "")
        values = facet.get("values", [])
        interesting = "brand" in code.lower() or "produsent" in name.lower() or "brand" in name.lower()
        marker = " <-- SER RELEVANT UT" if interesting else ""
        print(f"  facet code={code!r} name={name!r} ({len(values)} verdier){marker}")
        if interesting:
            for v in values[:30]:
                print(f"      code={v.get('code')!r}  name={v.get('name')!r}  count={v.get('count')}")

    print("\n=== Rådump av felter på første produkt (nøkler) ===")
    prods = data.get("products", [])
    if prods:
        print(sorted(prods[0].keys()))
        # Print anything that smells like brand/producer/manufacturer
        for k, v in prods[0].items():
            if any(s in k.lower() for s in ("brand", "produ", "manufact", "supplier", "goods")):
                print(f"  {k} = {v!r}")

if __name__ == "__main__":
    main()
