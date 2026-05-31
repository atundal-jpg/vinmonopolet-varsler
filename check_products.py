#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime

VINMONOPOLET_API_KEY = os.environ.get("VINMONOPOLET_API_KEY", "")
NTFY_TOPIC           = os.environ.get("NTFY_TOPIC", "")
NTFY_URL             = "https://ntfy.sh"

WATCH_LIST = [
    {"id": "11501901", "name": "Adrien Renoir Le Terroir Verzy Grand Cru Extra Brut"},
]

NEARBY_STORES = [
    "Bærum, Bekkestua","Bærum, Østerås","Oslo, CC Vest","Bærum, Fornebu",
    "Oslo, Røa","Bærum, Kolsås","Bærum, Sandvika","Bærum, Bærums Verk",
    "Oslo, Skøyen","Oslo, Frogner","Oslo, Vinderen","Oslo, Colosseum",
    "Oslo, Briskeby","Oslo, Valkyrien","Oslo, Aker Brygge","Oslo, Paleet",
    "Oslo, Ullevaal Stadion","Oslo, Steen & Strøm",
]

TRIGGER_AVAILABILITY = ["Kan bestilles","Ikke på lager - kan bestilles","På lager","Bestill"]
STATE_FILE = "data/state.json"

def fetch_availability(product_id):
    url = f"https://www.vinmonopolet.no/vmpws/v3/vmp/products/{product_id}/availability"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0","Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil: {e}")
    return None

def fetch_new_products():
    if not VINMONOPOLET_API_KEY:
        return []
    url = "https://apis.vinmonopolet.no/products/v0/details-normal?maxResults=100&start=0"
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": VINMONOPOLET_API_KEY,"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil: {e}")
    return []

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"seen_ids": [], "watch_status": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_notification(title, message, priority="high", tags="wine"):
    if not NTFY_TOPIC:
        return
    req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}", data=message.encode(),
        headers={"Title": title.encode(),"Priority": priority,"Tags": tags}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            print(f"    ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"    ⚠️  Varsel feilet: {e}")

def parse_store_hits(availability):
    hits = []
    for store in availability.get("storesAvailability", {}).get("infos", []):
        location = store.get("location", "")
        avail    = store.get("availability", "")
        readable = store.get("readableValue", "")
        if location not in NEARBY_STORES:
            continue
        if any(t.lower() in avail.lower() or t.lower() in readable.lower() for t in TRIGGER_AVAILABILITY):
            hits.append({"location": location, "availability": avail})
    return hits

def parse_delivery_hit(availability):
    delivery = availability.get("deliveryAvailability", {})
    if delivery.get("availableForPurchase", False):
        infos = delivery.get("infos", [])
        if infos:
            return infos[0].get("readableValue", "Tilgjengelig for levering")
    return None

def check_watch_list(state):
    if not WATCH_LIST:
        print("    ℹ️  Ingen produkter i WATCH_LIST ennå.")
        return state
    for item in WATCH_LIST:
        pid = str(item["id"])
        pname = item.get("name", f"Produkt {pid}")
        print(f"    🔍  Sjekker: {pname}")
        avail = fetch_availability(pid)
        if not avail:
            continue
        store_hits   = parse_store_hits(avail)
        delivery_hit = parse_delivery_hit(avail)
        prev = state["watch_status"].get(pid, {"stores": [], "delivery": False})
        prev_locs = {h["location"] for h in prev.get("stores", [])}
        new_hits = [h for h in store_hits if h["location"] not in prev_locs]
        if new_hits:
            lines = "\n".join(f"• {h['location']}: {h['availability']}" for h in new_hits)
            send_notification(f"🍷 {pname} tilgjengelig!",
                f"{pname} er nå tilgjengelig:\n\n{lines}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                "urgent", "wine,rotating_light")
        if delivery_hit and not prev.get("delivery"):
            send_notification(f"📦 {pname} kan bestilles!",
                f"{pname} er tilgjengelig for nettbestilling.\n{delivery_hit}\n\nhttps://www.vinmonopolet.no/p/{pid}",
                "high", "wine,package")
        if not store_hits and not delivery_hit:
            print(f"    📭  {pname}: ikke tilgjengelig.")
        state["watch_status"][pid] = {"stores": store_hits, "delivery": delivery_hit is not None, "last_checked": datetime.now().isoformat()}
    return state

def check_new_arrivals(state):
    if not VINMONOPOLET_API_KEY:
        print("    ℹ️  Ingen API-nøkkel – hopper over.")
        return state
    products = fetch_new_products()
    seen_ids = set(state.get("seen_ids", []))
    for p in products:
        pid = str(p.get("basic", {}).get("productId", ""))
        if pid not in seen_ids:
            name  = p.get("basic", {}).get("productLongName", "Ukjent")
            price = p.get("basic", {}).get("price", {}).get("value", "?")
            send_notification(f"🆕 Nytt: {name}", f"{name}\nPris: {price} kr\nhttps://www.vinmonopolet.no/p/{pid}", "default", "wine,new")
            seen_ids.add(pid)
    state["seen_ids"] = list(seen_ids)[-2000:]
    return state

def main():
    print(f"\n{'='*50}")
    print(f"  Vinmonopolet varsler – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")
    state = load_state()
    print("📋  Sjekker ønskeliste...")
    state = check_watch_list(state)
    print("\n📦  Sjekker nye produkter...")
    state = check_new_arrivals(state)
    save_state(state)
    print("\n✅  Ferdig!\n")

if __name__ == "__main__":
    main()
