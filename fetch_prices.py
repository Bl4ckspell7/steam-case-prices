import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypedDict
from urllib.parse import quote as urlquote

import requests

PRICE_URL: str = "https://steamcommunity.com/market/priceoverview/?currency=3&appid=730&market_hash_name="
LISTING_URL: str = "https://steamcommunity.com/market/listings/730/"
ITEMS_FILE: str = "items.json"
DELAY_SEC: float = 4.0
MAX_RETRIES: int = 3
RETRY_BACKOFF_SEC: float = 15.0
TIMEOUT_SEC: int = 15

_DASH_CENTS = re.compile(r"(\d),--(\s*€)")
_ITEM_ID = re.compile(r"G[0-9A-F]+$")


class Item(TypedDict):
    name: str
    id: str | None
    type: str


def _normalize_price(price: str | None) -> str | None:
    """Convert prices like '6,--€' to '6,00€'."""
    if price is None:
        return None
    return _DASH_CENTS.sub(r"\1,00\2", price)


def load_items() -> list[Item]:
    with open(ITEMS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_items(items: list[Item]) -> None:
    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _with_retries[T](attempt_fn: Callable[[], T | None], failure_msg: str) -> T | None:
    """Run attempt_fn up to MAX_RETRIES times with backoff; None means failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result: T | None = attempt_fn()
            if result is not None:
                return result

            print(f"  attempt {attempt}/{MAX_RETRIES} failed: {failure_msg}")
        except Exception as e:
            print(f"  attempt {attempt}/{MAX_RETRIES} failed: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SEC * attempt)

    return None


def resolve_id(name: str) -> str | None:
    """Resolve an item's market ID from the redirect of its name-based listing URL."""
    url: str = LISTING_URL + urlquote(name)

    def attempt() -> str | None:
        resp: requests.Response = requests.get(
            url, timeout=TIMEOUT_SEC, allow_redirects=False
        )
        match = _ITEM_ID.search(resp.headers.get("Location", ""))
        return match.group(0) if match else None

    return _with_retries(attempt, "no ID in redirect")


def resolve_missing_ids(items: list[Item]) -> None:
    """Fill in missing market IDs and persist them to the items file."""
    missing: list[Item] = [item for item in items if not item.get("id")]
    resolved: bool = False

    for i, item in enumerate(missing):
        if i > 0:
            time.sleep(DELAY_SEC)
        print(f"Resolving ID for {item['name']}")
        item_id: str | None = resolve_id(item["name"])
        if item_id:
            item["id"] = item_id
            resolved = True
            print(f"  -> {item_id}")

    if resolved:
        save_items(items)


def fetch_price(name: str, item_id: str | None = None) -> dict[str, str | None]:
    url: str = PRICE_URL + urlquote(item_id or name)

    def attempt() -> dict[str, str | None] | None:
        resp: requests.Response = requests.get(url, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        data: dict = resp.json()

        if not data.get("success"):
            return None

        return {
            "name": name,
            "median_price": _normalize_price(data.get("median_price")),
            "lowest_price": _normalize_price(data.get("lowest_price")),
            "volume": data.get("volume"),
        }

    result: dict[str, str | None] | None = _with_retries(attempt, "success=false")
    if result is not None:
        return result

    return {"name": name, "median_price": None, "lowest_price": None, "volume": None}


def main() -> None:
    items: list[Item] = load_items()
    resolve_missing_ids(items)

    results: list[dict[str, str | None]] = []

    for i, item in enumerate(items):
        print(f"[{i + 1:02d}/{len(items)}] {item['name']}")
        results.append(fetch_price(item["name"], item.get("id")))
        if i < len(items) - 1:
            time.sleep(DELAY_SEC)

    output: dict = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "prices": results,
    }

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    ok: int = sum(1 for r in results if r["median_price"] or r["lowest_price"])
    print(f"\nDone: {ok}/{len(items)} prices fetched")


if __name__ == "__main__":
    main()
