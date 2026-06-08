#!/usr/bin/env python3
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime

VINMONOPOLET_API_KEY = os.environ.get("VINMONOPOLET_API_KEY", "")
NTFY_TOPIC           = os.environ.get("NTFY_TOPIC", "")
NTFY_URL             = "https://ntfy.sh"
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY         = os.environ.get("SUPABASE_KEY", "")

STATE_FILE = "data/state.json"

# ─── Supabase ─────────────────────────────────────────────────────────────────

def supabase_get(table):
    """Henter alle rader fra en Supabase-tabell."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting fra Supabase ({table}): {e}")
    return []

# ─── Vinmonopolet availability (sanntid) ──────────────────────────────────────

def fetch_availability(product_id):
    url = f"https://www.vinmonopolet.no/vmpws/v3/vmp/products/{product_id}/availability"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
        "Referer": "https://www.vinmonopolet.no/",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting av tilgjengelighet for {product_id}: {e}")
    return None

def producer_products_in_nearby_stores(brand_key):
    """Returnerer en dict {product_id: [butikknavn, ...]} for produsentens
    produkter som finnes i brukerens nærbutikker.

    Gjør ett søk per nærbutikk (kombinerer availableInStores + brand),
    slik at vi vet nøyaktig hvilke produkter som ligger i hvilke butikker.
    """
    result = {}
    for store_name, store_code in NEARBY_STORE_CODES.items():
        query = f":relevance:availableInStores:{store_code}:brand:{brand_key}"
        params = urllib.parse.urlencode({
            "fields": "BASIC",
            "pageSize": 50,
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
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            for p in data.get("products", []):
                pid = str(p.get("code", ""))
                if pid:
                    result.setdefault(pid, []).append(store_name)
        except Exception as e:
            print(f"    ⚠️  Butikksjekk feilet ({store_name}, {brand_key}): {e}")
        time.sleep(1)
    return result

# ─── Vinmonopolet produktsøk (internt brand-endepunkt, ingen API-nøkkel) ──────

# Butikkoder for nærhetsfilter (verifisert mot Vinmonopolets offisielle butikkliste)
NEARBY_STORE_CODES = {
    "Bærum, Bekkestua": "190",
    "Bærum, Østerås": "198",
    "Oslo, CC Vest": "127",
    "Bærum, Fornebu": "442",
    "Oslo, Røa": "335",
    "Bærum, Kolsås": "124",
    "Bærum, Sandvika": "194",
    "Bærum, Bærums Verk": "453",
    "Oslo, Skøyen": "393",
    "Oslo, Frogner": "111",
    "Oslo, Vinderen": "454",
    "Oslo, Colosseum": "136",
    "Oslo, Briskeby": "104",
    "Oslo, Valkyrien": "471",
    "Oslo, Aker Brygge": "114",
    "Oslo, Paleet": "141",
    "Oslo, Ullevaal Stadion": "334",
    "Oslo, Steen & Strøm": "286",
}

CATEGORY_MAP = {
    "hvitvin": "hvitvin",
    "rødvin": "rødvin",
    "rosévin": "rosévin",
    "musserende": "musserende_vin",
    "sterkvin": "sterkvin",
    "brennevin": "brennevin",
}

def producer_to_brand_key(producer_name):
    """Konverterer produsentnavn til Vinmonopolets brand-nøkkelformat.
    Eks: 'Dom. Hubert Lamy' -> 'dom_hubert_lamy'
    """
    import re
    name = producer_name.lower()
    name = re.sub(r'[^a-zæøå0-9]+', '_', name)
    name = name.strip('_')
    return name

def search_products(producer_name, category=None):
    """Søker etter produkter fra en produsent via Vinmonopolets interne brand-søk."""
    brand_key = producer_to_brand_key(producer_name)

    # Bygg query med valgfritt kategorifilter
    query = f":name-asc:brand:{brand_key}"
    if category:
        cat_key = CATEGORY_MAP.get(category.lower(), category.lower())
        query += f":mainCategory:{cat_key}"

    params = urllib.parse.urlencode({
        "fields": "FULL",
        "pageSize": 50,
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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved søk etter {producer_name}: {e}")
        return []

    all_products = data.get("products", [])
    print(f"    🔎  Søk returnerte {len(all_products)} produkt(er) for '{producer_name}'")
    return all_products

# ─── Tilstandshåndtering ──────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"watch_status": {}, "producer_products": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ─── Varsling ─────────────────────────────────────────────────────────────────

def send_notification(title, message, priority="high", tags="wine"):
    if not NTFY_TOPIC:
        print(f"    ⚠️  NTFY_TOPIC ikke satt – hopper over: {title}")
        return
    req = urllib.request.Request(
        f"{NTFY_URL}/{NTFY_TOPIC}",
        data=message.encode(),
        headers={"Title": title.encode(), "Priority": priority, "Tags": tags},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            print(f"    ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"    ⚠️  Varsel feilet: {e}")

def product_nearby_stores(product_id):
    """Returnerer hvilke av brukerens nærbutikker som har ETT gitt produkt.

    Bruker fritekst-søk på produkt-ID. availableInStores-fasetten i svaret
    lister da alle butikker som har akkurat dette produktet – i ett kall.
    """
    query = f"{product_id}:relevance"
    params = urllib.parse.urlencode({
        "fields": "BASIC",
        "pageSize": 1,
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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Butikksjekk feilet for {product_id}: {e}")
        return []

    # Finn availableInStores-fasetten
    store_codes = set()
    for facet in data.get("facets", []):
        if facet.get("code") == "availableInStores":
            for v in facet.get("values", []):
                store_codes.add(str(v.get("code", "")))

    # Kryss mot brukerens nærbutikker
    code_to_name = {code: name for name, code in NEARBY_STORE_CODES.items()}
    return [code_to_name[c] for c in store_codes if c in code_to_name]

# ─── Sjekk enkeltprodukter ────────────────────────────────────────────────────

def check_watch_products(state):
    products = supabase_get("watch_products")
    if not products:
        print("    ℹ️  Ingen produkter i watch_products-tabellen.")
        return state

    for item in products:
        pid   = str(item.get("product_id", ""))
        pname = item.get("name", f"Produkt {pid}")
        if not pid:
            continue
        print(f"    🔍  Sjekker: {pname}")

        avail = fetch_availability(pid)
        if not avail:
            continue

        can_deliver = avail.get("deliveryAvailability", {}).get("availableForPurchase", False)

        # Butikk-presis sjekk: hvilke av DINE butikker har produktet?
        my_stores = product_nearby_stores(pid)
        in_store  = len(my_stores) > 0
        store_list = ", ".join(my_stores)

        prev = state["watch_status"].get(pid, {"in_store": False, "delivery": False})

        if in_store and not prev.get("in_store"):
            send_notification(
                title=f"🍷 {pname} finnes nær deg!",
                message=f"{pname}\nButikk: {store_list}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                priority="urgent", tags="wine,rotating_light"
            )
        elif not in_store and prev.get("in_store"):
            print(f"    📭  {pname}: ikke lenger i dine butikker.")

        if can_deliver and not prev.get("delivery"):
            send_notification(
                title=f"📦 {pname} kan bestilles!",
                message=f"{pname} er tilgjengelig for nettbestilling.\n\nhttps://www.vinmonopolet.no/p/{pid}",
                priority="high", tags="wine,package"
            )
        elif not can_deliver and prev.get("delivery"):
            print(f"    📭  {pname}: kan ikke lenger bestilles.")

        if not in_store and not can_deliver:
            print(f"    📭  {pname}: ikke i dine butikker / kan ikke bestilles.")

        state["watch_status"][pid] = {
            "in_store": in_store,
            "delivery": can_deliver,
            "stores": my_stores,
            "last_checked": datetime.now().isoformat(),
        }

        time.sleep(2)  # Pause mellom hvert produkt for å unngå rate-limiting

    return state

# ─── Sjekk produsenter ────────────────────────────────────────────────────────

def check_watch_producers(state):
    producers = supabase_get("watch_producers")
    if not producers:
        print("    ℹ️  Ingen produsenter i watch_producers-tabellen.")
        return state

    for item in producers:
        producer = item.get("producer_name", "").strip()
        category = item.get("category", "") or ""
        if not producer:
            continue

        label = f"{producer}" + (f" ({category})" if category else "")
        print(f"    🔍  Sjekker produsent: {label}")

        products = search_products(producer, category if category else None)
        if not products:
            print(f"    ℹ️  Ingen produkter funnet for {label}.")
            continue

        # Finn hvilke av produsentens produkter som ligger i DINE nærbutikker
        brand_key = producer_to_brand_key(producer)
        nearby = producer_products_in_nearby_stores(brand_key)

        # Hent tidligere kjente produkt-IDer for denne produsenten
        prev_ids = set(state.get("producer_products", {}).get(producer, []))
        current_ids = set()

        for p in products:
            pid  = str(p.get("code", ""))
            name = p.get("name", "Ukjent")
            if not pid:
                continue
            current_ids.add(pid)

            # Butikk-presis status: er produktet i en av DINE butikker?
            my_stores   = nearby.get(pid, [])
            in_store    = len(my_stores) > 0
            avail       = p.get("productAvailability", {})
            can_deliver = avail.get("deliveryAvailability", {}).get("availableForPurchase", False)
            price       = p.get("price", {}).get("formattedValue", "")
            store_list  = ", ".join(my_stores)

            prev_status = state.get("watch_status", {}).get(f"producer_{pid}", {})

            # Nytt produkt vi ikke har sett før
            if pid not in prev_ids:
                print(f"    🆕  Nytt produkt fra {producer}: {name}")
                if in_store:
                    send_notification(
                        title=f"🍷 {name} finnes nær deg!",
                        message=f"{name}\nPris: {price}\nButikk: {store_list}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                        priority="urgent", tags="wine,rotating_light"
                    )
                elif can_deliver:
                    send_notification(
                        title=f"📦 {name} kan bestilles!",
                        message=f"{name}\nPris: {price}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                        priority="high", tags="wine,package"
                    )
                else:
                    print(f"    📭  {name}: ikke i dine butikker / kan ikke bestilles ennå – overvåkes.")
            else:
                if in_store and not prev_status.get("in_store"):
                    send_notification(
                        title=f"🍷 {name} finnes nær deg!",
                        message=f"{name}\nPris: {price}\nButikk: {store_list}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                        priority="urgent", tags="wine,rotating_light"
                    )
                if can_deliver and not prev_status.get("delivery"):
                    send_notification(
                        title=f"📦 {name} kan bestilles!",
                        message=f"{name}\nPris: {price}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                        priority="high", tags="wine,package"
                    )

            state.setdefault("watch_status", {})[f"producer_{pid}"] = {
                "in_store": in_store,
                "delivery": can_deliver,
                "stores": my_stores,
                "last_checked": datetime.now().isoformat(),
            }

        # Oppdater kjente produkter for denne produsenten
        if "producer_products" not in state:
            state["producer_products"] = {}
        state["producer_products"][producer] = list(current_ids)

        time.sleep(2)  # Pause mellom hver produsent for å unngå rate-limiting

    return state

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Vinmonopolet varsler – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL eller SUPABASE_KEY mangler i miljøvariablene.")

    state = load_state()

    print("📋  Sjekker enkeltprodukter...")
    state = check_watch_products(state)

    print("\n🏭  Sjekker produsenter...")
    state = check_watch_producers(state)

    save_state(state)
    print("\n✅  Ferdig!\n")

if __name__ == "__main__":
    main()
