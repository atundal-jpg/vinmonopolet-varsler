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
 
STATE_FILE = "data/state.json"
 
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
        print(f"    ⚠️  Feil ved henting av {product_id}: {e}")
    return None
 
def fetch_new_products():
    if not VINMONOPOLET_API_KEY:
        return []
    url = "https://apis.vinmonopolet.no/products/v0/details-normal?maxResults=100&start=0"
    req = urllib.request.Request(url, headers={
        "Ocp-Apim-Subscription-Key": VINMONOPOLET_API_KEY,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    ⚠️  Feil ved henting av nye produkter: {e}")
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
 
def check_watch_list(state):
    if not WATCH_LIST:
        print("    ℹ️  Ingen produkter i WATCH_LIST ennå.")
        return state
 
    for item in WATCH_LIST:
        pid   = str(item["id"])
        pname = item.get("name", f"Produkt {pid}")
        print(f"    🔍  Sjekker: {pname}")
 
        avail = fetch_availability(pid)
        if not avail:
            continue
 
        stores   = avail.get("storesAvailability", {})
        delivery = avail.get("deliveryAvailability", {})
 
        in_store    = stores.get("availableForPurchase", False)
        can_deliver = delivery.get("availableForPurchase", False)
 
        prev       = state["watch_status"].get(pid, {"in_store": False, "delivery": False})
        prev_store = prev.get("in_store", False)
        prev_deliv = prev.get("delivery", False)
 
        # Varsel hvis vinen nå er tilgjengelig i butikk (og ikke var det sist)
        if in_store and not prev_store:
            send_notification(
                title=f"🍷 {pname} er i butikk!",
                message=(
                    f"{pname} er nå tilgjengelig i butikk.\n\n"
                    f"Sjekk hvilke butikker som har den:\n"
                    f"https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="urgent",
                tags="wine,rotating_light"
            )
        elif not in_store and prev_store:
            print(f"    📭  {pname}: ikke lenger i butikk.")
 
        # Varsel hvis vinen nå kan bestilles på nett (og ikke kunne det sist)
        if can_deliver and not prev_deliv:
            send_notification(
                title=f"📦 {pname} kan bestilles!",
                message=(
                    f"{pname} er nå tilgjengelig for nettbestilling.\n\n"
                    f"Bestill her: https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="high",
                tags="wine,package"
            )
        elif not can_deliver and prev_deliv:
            print(f"    📭  {pname}: kan ikke lenger bestilles på nett.")
 
        if not in_store and not can_deliver:
            print(f"    📭  {pname}: ikke tilgjengelig.")
 
        state["watch_status"][pid] = {
            "in_store": in_store,
            "delivery": can_deliver,
            "last_checked": datetime.now().isoformat(),
        }
 
    return state
 
def check_new_arrivals(state):
    if not VINMONOPOLET_API_KEY:
        print("    ℹ️  Ingen API-nøkkel – hopper over nye produkter.")
        return state
 
    products = fetch_new_products()
    seen_ids = set(state.get("seen_ids", []))
 
    for p in products:
        pid = str(p.get("basic", {}).get("productId", ""))
        if pid and pid not in seen_ids:
            name  = p.get("basic", {}).get("productLongName", "Ukjent")
            price = p.get("basic", {}).get("price", {}).get("value", "?")
            send_notification(
                title=f"🆕 Nytt: {name}",
                message=f"{name}\nPris: {price} kr\nhttps://www.vinmonopolet.no/p/{pid}",
                priority="default",
                tags="wine,new"
            )
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
