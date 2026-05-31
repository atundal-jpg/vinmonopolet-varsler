#!/usr/bin/env python3
"""
Vinmonopolet varsler - sjekker om ønskede produkter er tilgjengelig
og sender push-varsel via ntfy.sh
"""
 
import json
import os
import sys
import urllib.request
from datetime import datetime
 
# ─── Konfigurasjon ────────────────────────────────────────────────────────────
 
VINMONOPOLET_API_KEY = os.environ.get("VINMONOPOLET_API_KEY", "")
NTFY_TOPIC           = os.environ.get("NTFY_TOPIC", "")
NTFY_URL             = "https://ntfy.sh"
 
# Produkter du vil følge med på.
# Finn ID-en i URL-en på vinmonopolet.no/varer/.../p/ID
WATCH_LIST = [
    # {"id": "20491301", "name": "Eksempelvin 2020"},
]
 
# Butikker innenfor rekkevidde (nøyaktig slik de står i location-feltet fra API)
NEARBY_STORES = [
    "Bærum, Bekkestua",
    "Bærum, Østerås",
    "Oslo, CC Vest",
    "Bærum, Fornebu",
    "Oslo, Røa",
    "Bærum, Kolsås",
    "Bærum, Sandvika",
    "Bærum, Bærums Verk",
    "Oslo, Skøyen",
    "Oslo, Frogner",
    "Oslo, Vinderen",
    "Oslo, Colosseum",
    "Oslo, Briskeby",
    "Oslo, Valkyrien",
    "Oslo, Aker Brygge",
    "Oslo, Paleet",
    "Oslo, Ullevaal Stadion",
    "Oslo, Steen & Strøm",
]
 
# Lagerstatus-tekster som trigger varsel
TRIGGER_AVAILABILITY = [
    "Kan bestilles",
    "Ikke på lager - kan bestilles",
    "På lager",
    "Bestill",
]
 
STATE_FILE = "data/state.json"
 
# ─── Availability-endepunkt (sanntid, ingen API-nøkkel nødvendig) ─────────────
 
def fetch_availability(product_id: str) -> dict | None:
    """Henter sanntids lagerstatus fra Vinmonopolets interne API."""
    url = f"https://www.vinmonopolet.no/vmpws/v3/vmp/products/{product_id}/availability"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; vinmonopolet-varsler/1.0)",
            "Accept": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting av tilgjengelighet for {product_id}: {e}")
    return None
 
# ─── Nye produkter via offisielt API (daglig oppdatert) ───────────────────────
 
def fetch_new_products(max_results: int = 100) -> list[dict]:
    """Henter nyeste produkter fra det offisielle Vinmonopolet-APIet."""
    if not VINMONOPOLET_API_KEY:
        return []
    url = f"https://apis.vinmonopolet.no/products/v0/details-normal?maxResults={max_results}&start=0"
    req = urllib.request.Request(
        url,
        headers={
            "Ocp-Apim-Subscription-Key": VINMONOPOLET_API_KEY,
            "Accept": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting av nye produkter: {e}")
    return []
 
# ─── Tilstandshåndtering ──────────────────────────────────────────────────────
 
def load_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen_ids": [], "watch_status": {}}
 
def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
 
# ─── Varsling ─────────────────────────────────────────────────────────────────
 
def send_notification(title: str, message: str, priority: str = "high", tags: str = "wine"):
    if not NTFY_TOPIC:
        print(f"    ⚠️  NTFY_TOPIC ikke satt – hopper over varsel: {title}")
        return
    url = f"{NTFY_URL}/{NTFY_TOPIC}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": priority,
            "Tags": tags,
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            print(f"    ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"    ⚠️  Kunne ikke sende varsel: {e}")
 
# ─── Analyse av tilgjengelighet ───────────────────────────────────────────────
 
def parse_store_hits(availability: dict) -> list[dict]:
    """
    Returnerer en liste med butikker i nærheten som har varen tilgjengelig
    eller kan bestilles. Hver oppføring har 'location' og 'availability'.
    """
    hits = []
    stores = availability.get("storesAvailability", {}).get("infos", [])
 
    for store in stores:
        location     = store.get("location", "")
        avail_text   = store.get("availability", "")
        readable     = store.get("readableValue", "")
 
        # Sjekk om butikken er i nærheten
        if location not in NEARBY_STORES:
            continue
 
        # Sjekk om statusen er interessant
        is_triggered = any(
            trigger.lower() in avail_text.lower() or trigger.lower() in readable.lower()
            for trigger in TRIGGER_AVAILABILITY
        )
        if is_triggered:
            hits.append({"location": location, "availability": avail_text})
 
    return hits
 
 
def parse_delivery_hit(availability: dict) -> str | None:
    """Returnerer leveringsstatus hvis varen kan bestilles på nett."""
    delivery = availability.get("deliveryAvailability", {})
    if delivery.get("availableForPurchase", False):
        infos = delivery.get("infos", [])
        if infos:
            return infos[0].get("readableValue", "Tilgjengelig for levering")
    return None
 
# ─── Sjekk ønskeliste ─────────────────────────────────────────────────────────
 
def check_watch_list(state: dict) -> dict:
    if not WATCH_LIST:
        print("    ℹ️  Ingen produkter i WATCH_LIST – legg til produkter i scriptet.")
        return state
 
    for item in WATCH_LIST:
        pid   = str(item["id"])
        pname = item.get("name", f"Produkt {pid}")
        print(f"    🔍  Sjekker: {pname} (ID: {pid})")
 
        availability = fetch_availability(pid)
        if not availability:
            continue
 
        store_hits    = parse_store_hits(availability)
        delivery_hit  = parse_delivery_hit(availability)
        prev_status   = state["watch_status"].get(pid, {"stores": [], "delivery": False})
 
        prev_store_locations = {h["location"] for h in prev_status.get("stores", [])}
        new_store_hits = [h for h in store_hits if h["location"] not in prev_store_locations]
 
        # Varsel for nye butikker
        if new_store_hits:
            store_lines = "\n".join(
                f"• {h['location']}: {h['availability']}" for h in new_store_hits
            )
            send_notification(
                title=f"🍷 {pname} tilgjengelig!",
                message=(
                    f"{pname} er nå tilgjengelig i disse butikkene:\n\n"
                    f"{store_lines}\n\n"
                    f"Se mer: https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="urgent",
                tags="wine,rotating_light"
            )
 
        # Varsel for nettbestilling (kun hvis endret siden sist)
        if delivery_hit and not prev_status.get("delivery", False):
            send_notification(
                title=f"📦 {pname} kan bestilles på nett!",
                message=(
                    f"{pname} er nå tilgjengelig for nettbestilling.\n"
                    f"{delivery_hit}\n\n"
                    f"Bestill her: https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="high",
                tags="wine,package"
            )
 
        if not store_hits and not delivery_hit:
            print(f"    📭  {pname}: ikke tilgjengelig i nærheten.")
 
        # Oppdater tilstand
        state["watch_status"][pid] = {
            "stores": store_hits,
            "delivery": delivery_hit is not None,
            "last_checked": datetime.now().isoformat(),
        }
 
    return state
 
# ─── Sjekk nye produkter ──────────────────────────────────────────────────────
 
def check_new_arrivals(state: dict) -> dict:
    if not VINMONOPOLET_API_KEY:
        print("    ℹ️  VINMONOPOLET_API_KEY ikke satt – hopper over sjekk av nye produkter.")
        return state
 
    print("    🔍  Henter nyeste produkter...")
    products = fetch_new_products()
    seen_ids = set(state.get("seen_ids", []))
    new_products = [
        p for p in products
        if str(p.get("basic", {}).get("productId", "")) not in seen_ids
    ]
 
    if new_products:
        print(f"    🆕  Fant {len(new_products)} nye produkter!")
        for p in new_products[:5]:
            basic = p.get("basic", {})
            pid   = str(basic.get("productId", ""))
            name  = basic.get("productLongName", "Ukjent produkt")
            price = basic.get("price", {}).get("value", "?")
            send_notification(
                title=f"🆕 Nytt produkt: {name}",
                message=(
                    f"{name} er nå i sortimentet.\n"
                    f"Pris: {price} kr\n\n"
                    f"Se mer: https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="default",
                tags="wine,new"
            )
            seen_ids.add(pid)
    else:
        print("    ✓  Ingen nye produkter funnet.")
 
    state["seen_ids"] = list(seen_ids)[-2000:]
    return state
 
# ─── Main ─────────────────────────────────────────────────────────────────────
 
def main():
    print(f"\n{'='*50}")
    print(f"  Vinmonopolet varsler – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")
 
    state = load_state()
 
    print("📋  Sjekker ønskeliste (sanntid)...")
    state = check_watch_list(state)
 
    print("\n📦  Sjekker nye produkter (offisielt API)...")
    state = check_new_arrivals(state)
 
    save_state(state)
    print(f"\n✅  Ferdig!\n")
 
if __name__ == "__main__":
    main()
