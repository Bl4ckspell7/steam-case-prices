import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote as urlquote

import requests

BASE_URL: str = "https://steamcommunity.com/market/priceoverview/?currency=3&appid=730&market_hash_name="
DELAY_SEC: float = 4.0
MAX_RETRIES: int = 3
RETRY_BACKOFF_SEC: float = 15.0
TIMEOUT_SEC: int = 15

_DASH_CENTS = re.compile(r"(\d),--(\s*€)")

ITEMS: list[str] = [
    "Chroma 2 Case",
    "Chroma 3 Case",
    "Chroma Case",
    "Clutch Case",
    "CS:GO Weapon Case 2",
    "CS:GO Weapon Case 3",
    "Danger Zone Case",
    "Dreams & Nightmares Case",
    "Falchion Case",
    "Fracture Case",
    "Gallery Case",
    "Gamma Case",
    "Glove Case",
    "Horizon Case",
    "Operation Breakout Weapon Case",
    "Operation Broken Fang Case",
    "Operation Hydra Case",
    "Operation Phoenix Weapon Case",
    "Operation Vanguard Weapon Case",
    "Operation Wildfire Case",
    "Prisma 2 Case",
    "Prisma Case",
    "Revolver Case",
    "Shadow Case",
    "Shattered Web Case",
    "Snakebite Case",
    "Spectrum 2 Case",
    "Spectrum Case",
]


def _normalize_price(price: str | None) -> str | None:
    """Convert prices like '6,--€' to '6,00€'."""
    if price is None:
        return None
    return _DASH_CENTS.sub(r"\1,00\2", price)


def fetch_price(name: str) -> dict[str, str | None]:
    url: str = BASE_URL + urlquote(name)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp: requests.Response = requests.get(url, timeout=TIMEOUT_SEC)
            resp.raise_for_status()
            data: dict = resp.json()

            if data.get("success"):
                return {
                    "name": name,
                    "median_price": _normalize_price(data.get("median_price")),
                    "lowest_price": _normalize_price(data.get("lowest_price")),
                    "volume": data.get("volume"),
                }

            print(f"  attempt {attempt}/{MAX_RETRIES} failed: success=false")
        except Exception as e:
            print(f"  attempt {attempt}/{MAX_RETRIES} failed: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SEC * attempt)

    return {"name": name, "median_price": None, "lowest_price": None, "volume": None}


def main() -> None:
    results: list[dict[str, str | None]] = []

    for i, name in enumerate(ITEMS):
        print(f"[{i + 1:02d}/{len(ITEMS)}] {name}")
        results.append(fetch_price(name))
        if i < len(ITEMS) - 1:
            time.sleep(DELAY_SEC)

    output: dict = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "prices": results,
    }

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    ok: int = sum(1 for r in results if r["median_price"] or r["lowest_price"])
    print(f"\nDone: {ok}/{len(ITEMS)} prices fetched")


if __name__ == "__main__":
    main()
