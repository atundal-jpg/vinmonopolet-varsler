#!/usr/bin/env python3
"""Engangs-diagnoseskript: bekreft at kategori-koden er den faktiske synderen
for Elise Bougy, ikke brand-nøkkelen. Slettes etter bruk."""
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
    # Reproduser EKSAKT det check_products.py sender i dag for Elise Bougy
    # (category = 'Musserende vin' fra Supabase -> .lower() -> 'musserende vin',
    # som IKKE er en nøkkel i CATEGORY_MAP -> faller tilbake til seg selv).
    try_query("Produksjons-query (bug, kategori med mellomrom)",
              ":name-asc:brand:elise_bougy:mainCategory:musserende vin")

    # Riktig kode (underscore), som vi vet fungerer fra forrige kjøring.
    try_query("Riktig kategori-kode (underscore)",
              ":name-asc:brand:elise_bougy:mainCategory:musserende_vin")

    # Samme test, men på fallback-søket (fritekst) slik det faktisk bygges
    # i search_products() sin fallback-gren i dag.
    try_query("Fallback-søk MED samme bug i kategori",
              "Elise Bougy:relevance:mainCategory:musserende vin")
    try_query("Fallback-søk med riktig kategori-kode",
              "Elise Bougy:relevance:mainCategory:musserende_vin")

if __name__ == "__main__":
    main()
