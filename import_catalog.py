#!/usr/bin/env python3
"""
Importerer Vinmonopolets vinsortiment (rødvin, hvitvin, musserende)
i prissjiktet 300–1500 kr, 75cl, til Supabase-tabellen 'products'.

Bruker det offisielle Vinmonopolet-APIet (details-normal) med API-nøkkel.
Henter alt i bolker og filtrerer på kategori, pris og volum.
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

VINMONOPOLET_API_KEY = os.environ.get("VINMONOPOLET_API_KEY", "")
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY         = os.environ.get("SUPABASE_KEY", "")

# Filtre
PRICE_MIN   = 300
PRICE_MAX   = 1500
VOLUME_MIN  = 70    # cl (for å fange 75cl)
VOLUME_MAX  = 100   # cl
BATCH_SIZE  = 1000  # produkter per API-kall

# Kategorier vi vil ha (matches mot classification.mainProductTypeName)
WANTED_CATEGORIES = ["rødvin", "hvitvin", "musserende"]

# ─── Vinmonopolet offisielt API ───────────────────────────────────────────────

def fetch_batch(start):
    """Henter en bolk med produkter fra details-normal."""
    params = urllib.parse.urlencode({
        "maxResults": BATCH_SIZE,
        "start": start,
        "subscription-key": VINMONOPOLET_API_KEY,
    })
    url = f"https://apis.vinmonopolet.no/products/v0/details-normal?{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting (start={start}): {e}")
        return None

def get_category(product):
    """Henter hovedkategori fra classification."""
    classification = product.get("classification", {})
    return (classification.get("mainProductTypeName", "") or "").lower()

def get_price(product):
    """Henter gyldig salgspris."""
    prices = product.get("prices", [])
    for p in prices:
        sp = p.get("salesPrice")
        if sp:
            return sp
    return None

def parse_product(product):
    """Trekker ut relevante felter, returnerer None hvis utenfor filter."""
    basic = product.get("basic", {})

    # Volum (i liter i APIet, gjør om til cl)
    volume_l = basic.get("volume")
    if volume_l is None:
        return None
    volume_cl = volume_l * 100
    if volume_cl < VOLUME_MIN or volume_cl > VOLUME_MAX:
        return None

    # Kategori
    category = get_category(product)
    if not any(cat in category for cat in WANTED_CATEGORIES):
        return None

    # Pris
    price = get_price(product)
    if price is None or price < PRICE_MIN or price > PRICE_MAX:
        return None

    # Opprinnelse
    origin = product.get("origins", {}).get("origin", {})

    # Utvalg
    assortment = product.get("assortment", {}).get("assortment", "")

    try:
        pid = int(basic.get("productId", 0))
    except (ValueError, TypeError):
        return None

    return {
        "product_id": pid,
        "name":       basic.get("productLongName", ""),
        "price":      price,
        "category":   product.get("classification", {}).get("mainProductTypeName", ""),
        "country":    origin.get("country", ""),
        "region":     origin.get("region", ""),
        "producer":   "",  # finnes ikke i details-normal
        "selection":  assortment,
        "volume":     volume_cl,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

# ─── Supabase ─────────────────────────────────────────────────────────────────

def supabase_upsert(rows):
    """Upsert produkter i Supabase."""
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/products?on_conflict=product_id"
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            pass
    except Exception as e:
        print(f"    ⚠️  Supabase upsert-feil: {e}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Vinmonopolet katalog-import – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    if not VINMONOPOLET_API_KEY:
        print("❌  VINMONOPOLET_API_KEY mangler.")
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌  SUPABASE_URL eller SUPABASE_KEY mangler.")
        return

    start = 0
    total_seen = 0
    total_imported = 0
    batch_num = 0

    while True:
        batch_num += 1
        print(f"📦  Henter bolk {batch_num} (start={start})...")
        products = fetch_batch(start)

        if products is None:
            print("    ⚠️  Stopper pga feil.")
            break
        if not products:
            print("    ✓  Ingen flere produkter.")
            break

        total_seen += len(products)

        # Parse og filtrer
        matching = []
        for p in products:
            row = parse_product(p)
            if row:
                matching.append(row)

        # Lagre i Supabase
        if matching:
            supabase_upsert(matching)
            total_imported += len(matching)

        print(f"    ✓  {len(products)} hentet, {len(matching)} i prissjiktet (totalt {total_imported})")

        # Hvis vi fikk færre enn BATCH_SIZE er vi ferdig
        if len(products) < BATCH_SIZE:
            break

        start += BATCH_SIZE
        time.sleep(1.0)  # Vær snill mot APIet (60/min grense)

    print(f"\n✅  Ferdig! {total_seen} produkter gjennomgått, {total_imported} importert i prissjiktet.\n")

if __name__ == "__main__":
    main()
