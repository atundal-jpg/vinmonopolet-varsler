#!/usr/bin/env python3
import json
import os
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
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting av tilgjengelighet for {product_id}: {e}")
    return None

# ─── Vinmonopolet produktsøk (internt brand-endepunkt, ingen API-nøkkel) ──────

# Butikkoder for nærhetsfilter (hentet fra Vinmonopolets API)
NEARBY_STORE_CODES = {
    "Bærum, Bekkestua": "423",
    "Bærum, Østerås": "422",
    "Oslo, CC Vest": "306",
    "Bærum, Fornebu": "452",
    "Oslo, Røa": "303",
    "Bærum, Kolsås": "421",
    "Bærum, Sandvika": "420",
    "Bærum, Bærums Verk": "453",
    "Oslo, Skøyen": "305",
    "Oslo, Frogner": "302",
    "Oslo, Vinderen": "304",
    "Oslo, Colosseum": "308",
    "Oslo, Briskeby": "301",
    "Oslo, Valkyrien": "309",
    "Oslo, Aker Brygge": "307",
    "Oslo, Paleet": "300",
    "Oslo, Ullevaal Stadion": "310",
    "Oslo, Steen & Strøm": "311",
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
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
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

        in_store    = avail.get("storesAvailability", {}).get("availableForPurchase", False)
        can_deliver = avail.get("deliveryAvailability", {}).get("availableForPurchase", False)
        prev        = state["watch_status"].get(pid, {"in_store": False, "delivery": False})

        if in_store and not prev.get("in_store"):
            send_notification(
                title=f"🍷 {pname} er i butikk!",
                message=f"{pname} er nå tilgjengelig i butikk.\n\nSjekk butikker:\nhttps://www.vinmonopolet.no/p/{pid}",
                priority="urgent", tags="wine,rotating_light"
            )
        elif not in_store and prev.get("in_store"):
            print(f"    📭  {pname}: ikke lenger i butikk.")

        if can_deliver and not prev.get("delivery"):
            send_notification(
                title=f"📦 {pname} kan bestilles!",
                message=f"{pname} er tilgjengelig for nettbestilling.\n\nhttps://www.vinmonopolet.no/p/{pid}",
                priority="high", tags="wine,package"
            )
        elif not can_deliver and prev.get("delivery"):
            print(f"    📭  {pname}: kan ikke lenger bestilles.")

        if not in_store and not can_deliver:
            print(f"    📭  {pname}: ikke tilgjengelig.")

        state["watch_status"][pid] = {
            "in_store": in_store,
            "delivery": can_deliver,
            "last_checked": datetime.now().isoformat(),
        }

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

        # Hent tidligere kjente produkt-IDer for denne produsenten
        prev_ids = set(state.get("producer_products", {}).get(producer, []))
        current_ids = set()

        for p in products:
            pid  = str(p.get("code", ""))
            name = p.get("name", "Ukjent")
            if not pid:
                continue
            current_ids.add(pid)

            # Tilgjengelighet ligger allerede i søkeresultatet
            avail       = p.get("productAvailability", {})
            in_store    = avail.get("storesAvailability", {}).get("availableForPurchase", False)
            can_deliver = avail.get("deliveryAvailability", {}).get("availableForPurchase", False)
            price       = p.get("price", {}).get("formattedValue", "")

            # Nytt produkt vi ikke har sett før
            if pid not in prev_ids:
                print(f"    🆕  Nytt produkt fra {producer}: {name}")
                status = "tilgjengelig i butikk" if in_store else ("kan bestilles på nett" if can_deliver else "ikke tilgjengelig ennå")
                send_notification(
                    title=f"🆕 Nytt fra {producer}: {name}",
                    message=(
                        f"{name}\n"
                        f"Pris: {price}\n"
                        f"Status: {status}\n\n"
                        f"https://www.vinmonopolet.no/p/{pid}"
                    ),
                    priority="high", tags="wine,new"
                )
            # Kjent produkt – sjekk om tilgjengelighet har endret seg
            else:
                prev_status = state.get("watch_status", {}).get(f"producer_{pid}", {})
                if in_store and not prev_status.get("in_store"):
                    send_notification(
                        title=f"🍷 {name} er i butikk!",
                        message=f"{name}\nPris: {price}\n\nhttps://www.vinmonopolet.no/p/{pid}",
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
                "last_checked": datetime.now().isoformat(),
            }

        # Oppdater kjente produkter for denne produsenten
        if "producer_products" not in state:
            state["producer_products"] = {}
        state["producer_products"][producer] = list(current_ids)

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
