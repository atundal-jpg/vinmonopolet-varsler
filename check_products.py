#!/usr/bin/env python3
"""
Vinmonopolet varsler - sjekker om ønskede produkter er tilgjengelig
og sender push-varsel via ntfy.sh
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime

# ─── Konfigurasjon ────────────────────────────────────────────────────────────

# Sett disse i GitHub Secrets / miljøvariabler
VINMONOPOLET_API_KEY = os.environ.get("VINMONOPOLET_API_KEY", "")
NTFY_TOPIC          = os.environ.get("NTFY_TOPIC", "")          # f.eks. "vinvarsler-xk7q92"
NTFY_URL            = "https://ntfy.sh"

# Produkter du ønsker å følge med på.
# Legg til produkt-ID-er fra Vinmonopolet (tallene i URL-en på vinmonopolet.no)
# Eksempel: https://www.vinmonopolet.no/varer/vin/rødvin/chateau-margaux-2018/p/12345
# → ID er "12345"
WATCH_LIST = [
    # {"id": "12345", "name": "Château Margaux 2018"},
    # {"id": "67890", "name": "Romanée-Conti 2019"},
]

# Fil for å lagre forrige tilstand (sjekkes mot ny tilstand)
STATE_FILE = "data/state.json"

# ─── API-kall ─────────────────────────────────────────────────────────────────

def fetch_product(product_id: str) -> dict | None:
    """Henter produktinfo fra Vinmonopolet API."""
    url = f"https://apis.vinmonopolet.no/products/v0/details-normal?productId={product_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Ocp-Apim-Subscription-Key": VINMONOPOLET_API_KEY,
            "Accept": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data:
                return data[0]
    except Exception as e:
        print(f"  ⚠️  Feil ved henting av produkt {product_id}: {e}")
    return None


def fetch_new_products(max_results: int = 50) -> list[dict]:
    """Henter nylig tilgjengeliggjorte produkter fra Vinmonopolet API."""
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
        print(f"  ⚠️  Feil ved henting av nye produkter: {e}")
    return []

# ─── Tilstandshåndtering ──────────────────────────────────────────────────────

def load_state() -> dict:
    """Laster forrige kjøring sin tilstand."""
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen_ids": [], "watch_status": {}}


def save_state(state: dict):
    """Lagrer nåværende tilstand."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ─── Varsling ─────────────────────────────────────────────────────────────────

def send_notification(title: str, message: str, priority: str = "high", tags: str = "wine"):
    """Sender push-varsel via ntfy.sh."""
    if not NTFY_TOPIC:
        print(f"  ⚠️  NTFY_TOPIC ikke satt – hopper over varsel: {title}")
        return

    url = f"{NTFY_URL}/{NTFY_TOPIC}"
    data = message.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Title": title.encode("utf-8"),
            "Priority": priority,
            "Tags": tags,
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"  ✅  Varsel sendt: {title}")
    except Exception as e:
        print(f"  ⚠️  Kunne ikke sende varsel: {e}")

# ─── Logikk ───────────────────────────────────────────────────────────────────

def check_watch_list(state: dict) -> dict:
    """Sjekker om produkter på ønskelisten er blitt tilgjengelig."""
    if not WATCH_LIST:
        print("  ℹ️  Ingen produkter i WATCH_LIST – hopper over.")
        return state

    for item in WATCH_LIST:
        pid   = item["id"]
        pname = item.get("name", f"Produkt {pid}")
        print(f"  🔍  Sjekker: {pname} (ID: {pid})")

        product = fetch_product(pid)
        if not product:
            continue

        stock_info  = product.get("stocks", [])
        in_stock    = any(s.get("stockLevel", 0) > 0 for s in stock_info)
        was_in_stock = state["watch_status"].get(pid, False)

        if in_stock and not was_in_stock:
            # Ny tilgjengelighet!
            store_count = sum(1 for s in stock_info if s.get("stockLevel", 0) > 0)
            send_notification(
                title=f"🍷 {pname} er tilgjengelig!",
                message=(
                    f"{pname} er nå på lager hos {store_count} butikk(er).\n"
                    f"Sjekk: https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="urgent",
                tags="wine,rotating_light"
            )
        elif not in_stock and was_in_stock:
            print(f"  📭  {pname} er nå utsolgt.")

        state["watch_status"][pid] = in_stock

    return state


def check_new_arrivals(state: dict) -> dict:
    """Sjekker om det er kommet nye produkter siden siste kjøring."""
    print("  🔍  Henter nyeste produkter...")
    products = fetch_new_products(max_results=100)

    seen_ids = set(state.get("seen_ids", []))
    new_products = [p for p in products if str(p.get("basic", {}).get("productId", "")) not in seen_ids]

    if new_products:
        print(f"  🆕  Fant {len(new_products)} nye produkter!")
        for p in new_products[:5]:  # varsle maks 5 om gangen for å ikke spamme
            basic = p.get("basic", {})
            pid   = str(basic.get("productId", ""))
            name  = basic.get("productLongName", "Ukjent produkt")
            price = basic.get("price", {}).get("value", "?")

            send_notification(
                title=f"🆕 Nytt produkt: {name}",
                message=(
                    f"Nytt produkt tilgjengelig: {name}\n"
                    f"Pris: {price} kr\n"
                    f"Se mer: https://www.vinmonopolet.no/p/{pid}"
                ),
                priority="default",
                tags="wine,new"
            )
            seen_ids.add(pid)
    else:
        print("  ✓  Ingen nye produkter funnet.")

    # Hold kun de siste 2000 ID-ene for å unngå at filen vokser ubegrenset
    state["seen_ids"] = list(seen_ids)[-2000:]
    return state


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Vinmonopolet varsler – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    if not VINMONOPOLET_API_KEY:
        print("❌  VINMONOPOLET_API_KEY er ikke satt. Sett den i GitHub Secrets.")
        sys.exit(1)

    state = load_state()

    print("📋  Sjekker ønskeliste...")
    state = check_watch_list(state)

    print("\n📦  Sjekker nye produkter...")
    state = check_new_arrivals(state)

    save_state(state)
    print(f"\n✅  Ferdig! Tilstand lagret i {STATE_FILE}\n")


if __name__ == "__main__":
    main()
