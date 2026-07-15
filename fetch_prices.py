import json
import os
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
PRICES_FILE: str = "prices.json"
DELAY_SEC: float = 6.0
MAX_RETRIES: int = 3
RETRY_BACKOFF_SEC: float = 60.0
TIMEOUT_SEC: int = 15

SESSION: requests.Session = requests.Session()

_DASH_CENTS = re.compile(r"(\d),--(\s*€)")
_ITEM_ID = re.compile(r"G[0-9A-F]+$")

# Item types whose market variants share one family listing ID.
VARIANT_TYPES: frozenset[str] = frozenset({"skin"})


class Item(TypedDict):
    name: str
    id: str | None
    type: str


class PriceData(TypedDict):
    name: str
    id: str | None
    median_price: str | None
    lowest_price: str | None
    volume: str | None


class Price(PriceData):
    updated_at: str | None


def _read_slice_env() -> tuple[int, int]:
    """Read (SLICE_COUNT, SLICE_INDEX) from env; default to a single full slice."""
    count: int = int(os.environ.get("SLICE_COUNT", "1"))
    index: int = int(os.environ.get("SLICE_INDEX", "0"))
    if count < 1 or not (0 <= index < count):
        raise ValueError(f"invalid slice: SLICE_COUNT={count} SLICE_INDEX={index}")
    return count, index


def load_prices() -> dict[str, Price]:
    """Load the existing snapshot into a name→entry map (empty if absent)."""
    try:
        with open(PRICES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError, json.JSONDecodeError:
        return {}
    return {entry["name"]: entry for entry in data.get("prices", [])}


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
        resp: requests.Response = SESSION.get(
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


def fetch_price(name: str, item_id: str | None = None) -> PriceData:
    url: str = PRICE_URL + urlquote(item_id or name)

    def attempt() -> PriceData | None:
        resp: requests.Response = SESSION.get(url, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        data: dict = resp.json()

        if not data.get("success"):
            return None

        return {
            "name": name,
            "id": item_id,
            "median_price": _normalize_price(data.get("median_price")),
            "lowest_price": _normalize_price(data.get("lowest_price")),
            "volume": data.get("volume"),
        }

    result: PriceData | None = _with_retries(attempt, "success=false")
    if result is not None:
        return result

    return {
        "name": name,
        "id": item_id,
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }


def main() -> None:
    items: list[Item] = load_items()
    resolve_missing_ids(items)

    slice_count, slice_index = _read_slice_env()
    existing: dict[str, Price] = load_prices()
    now: str = datetime.now(timezone.utc).isoformat()

    # Fetch only this run's slice (stride: items i, i+count, i+2*count, …) and
    # carry over everything else from the previous snapshot, so a short run stays
    # under Steam's per-IP request budget while prices.json keeps every item.
    results: list[Price] = []
    fetched: int = 0

    for i, item in enumerate(items):
        name: str = item["name"]
        if i % slice_count != slice_index:
            results.append(existing.get(name) or _placeholder(item))
            continue

        print(f"[{i + 1:02d}/{len(items)}] {name}")
        # Steam maps all variants of a skin (wear, StatTrak) to one shared
        # family listing ID whose priceoverview data is aggregated — skins must
        # be fetched by name to get the variant's own price.
        item_id: str | None = None if item["type"] in VARIANT_TYPES else item.get("id")
        price: PriceData = fetch_price(name, item_id)
        entry: Price = {
            "name": price["name"],
            "id": price["id"],
            "median_price": price["median_price"],
            "lowest_price": price["lowest_price"],
            "volume": price["volume"],
            "updated_at": now,
        }
        results.append(entry)
        fetched += 1
        if i + slice_count < len(items):
            time.sleep(DELAY_SEC)

    output: dict = {"updated_at": now, "prices": results}

    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    ok: int = sum(1 for r in results if r["median_price"] or r["lowest_price"])
    print(f"\nDone: fetched {fetched} this slice, {ok}/{len(items)} priced total")


def _placeholder(item: Item) -> Price:
    """Null-price entry for an item not yet fetched into the snapshot."""
    return {
        "name": item["name"],
        "id": item.get("id"),
        "median_price": None,
        "lowest_price": None,
        "volume": None,
        "updated_at": None,
    }


if __name__ == "__main__":
    main()
