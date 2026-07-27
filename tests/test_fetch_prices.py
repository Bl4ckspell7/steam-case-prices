import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from fetch_prices import (
    SESSION,
    RateLimited,
    _normalize_price,
    fetch_price,
    main,
    resolve_id,
    resolve_missing_ids,
)


# --- integration ---


_PRICE_RE = re.compile(r"^\d+,\d{2}\s*€$")


def _assert_valid_prices(result: dict) -> None:
    if result["median_price"] is None and result["lowest_price"] is None:
        # No usable data means Steam was unreachable or rate-limited (429),
        # which is common from shared CI runner IPs — skip rather than fail,
        # so a real API-shape change still fails on a successful response.
        pytest.skip("Steam returned no price (rate-limited or unreachable)")

    for field in ("median_price", "lowest_price"):
        value = result[field]
        if value is not None:
            assert _PRICE_RE.match(value), f"{field} has unexpected format: {value!r}"

    assert result["volume"] is not None
    assert result["volume"].replace(",", "").isdigit(), (
        f"volume has unexpected format: {result['volume']!r}"
    )


@pytest.mark.integration
def test_fetch_price_real_request():
    try:
        result = fetch_price("Chroma Case")
    except RateLimited:
        pytest.skip("Steam rate-limited this runner")

    assert result["name"] == "Chroma Case"
    _assert_valid_prices(result)


@pytest.mark.integration
def test_fetch_price_by_id_real_request():
    try:
        result = fetch_price("Chroma Case", "G18DD1F3004")
    except RateLimited:
        pytest.skip("Steam rate-limited this runner")

    assert result["name"] == "Chroma Case"
    assert result["id"] == "G18DD1F3004"
    _assert_valid_prices(result)


@pytest.mark.integration
def test_resolve_id_real_request():
    result = resolve_id("Chroma Case")
    if result is None:
        pytest.skip("Steam unreachable or rate-limited")
    assert result == "G18DD1F3004"


# --- _normalize_price ---


def test_normalize_price_dash_cents():
    assert _normalize_price("6,-- €") == "6,00 €"


def test_normalize_price_normal():
    assert _normalize_price("6,50 €") == "6,50 €"


def test_normalize_price_none():
    assert _normalize_price(None) is None


def test_normalize_price_strips_thousands_separator():
    # Steam's real format for prices >= 1000, which Sheets cannot parse
    assert _normalize_price("1 127,42€") == "1127,42€"
    assert _normalize_price("1 234 567,89€") == "1234567,89€"


def test_normalize_price_strips_non_breaking_space():
    assert _normalize_price("1\xa0127,42€") == "1127,42€"


def test_normalize_price_thousands_and_dash_cents():
    assert _normalize_price("2 500,--€") == "2500,00€"


# --- resolve_id ---


def _mock_redirect(location: str | None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 302 if location else 200
    resp.headers = {"Location": location} if location else {}
    return resp


@patch("fetch_prices.SESSION.get")
def test_resolve_id_parses_redirect(mock_get):
    mock_get.return_value = _mock_redirect(
        "https://steamcommunity.com/market/listings/730/G18F91F3004"
    )

    assert resolve_id("Chroma 2 Case") == "G18F91F3004"
    assert mock_get.call_args.kwargs["allow_redirects"] is False
    # requests an HTML page, so announce text/html (not the JSON priceoverview)
    assert mock_get.call_args.kwargs["headers"]["Accept"] == "text/html"


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.SESSION.get")
def test_resolve_id_no_redirect_returns_none(mock_get, mock_sleep):
    mock_get.return_value = _mock_redirect(None)

    assert resolve_id("Unknown Item") is None
    assert mock_get.call_count == 3


# --- resolve_missing_ids ---


def _write_items(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items), encoding="utf-8")


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.resolve_id")
def test_resolve_missing_ids_fills_and_saves(
    mock_resolve_id, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    mock_resolve_id.return_value = "G18F91F3004"
    items = [
        {"name": "Chroma 2 Case", "id": None, "type": "case"},
        {"name": "Chroma Case", "id": "G18DD1F3004", "type": "case"},
    ]

    resolve_missing_ids(items)

    mock_resolve_id.assert_called_once_with("Chroma 2 Case")
    assert items[0]["id"] == "G18F91F3004"
    saved = json.loads(Path("items.json").read_text(encoding="utf-8"))
    assert saved == items


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.resolve_id")
def test_resolve_missing_ids_no_save_when_unresolved(
    mock_resolve_id, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    mock_resolve_id.return_value = None
    items = [{"name": "Unknown Item", "id": None, "type": "case"}]

    resolve_missing_ids(items)

    assert items[0]["id"] is None
    assert not Path("items.json").exists()


# --- fetch_price ---


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


@patch("fetch_prices.SESSION.get")
def test_fetch_price_success(mock_get):
    mock_get.return_value = _mock_response(
        {
            "success": True,
            "median_price": "6,50 €",
            "lowest_price": "6,00 €",
            "volume": "1,234",
        }
    )

    result = fetch_price("Chroma Case")

    assert result == {
        "name": "Chroma Case",
        "id": None,
        "median_price": "6,50 €",
        "lowest_price": "6,00 €",
        "volume": "1,234",
    }


def test_session_identifies_as_browser():
    # Steam 429s obvious bot clients harder; never fall back to the default
    # "python-requests/x.y" User-Agent.
    assert "Mozilla" in SESSION.headers["User-Agent"]
    assert "python-requests" not in SESSION.headers["User-Agent"]


@patch("fetch_prices.SESSION.get")
def test_fetch_price_sends_listing_referer(mock_get):
    mock_get.return_value = _mock_response(
        {"success": True, "median_price": "6,50 €", "lowest_price": None, "volume": "1"}
    )

    fetch_price("Chroma Case", "G18DD1F3004")

    referer = mock_get.call_args.kwargs["headers"]["Referer"]
    assert referer == "https://steamcommunity.com/market/listings/730/G18DD1F3004"


@patch("fetch_prices.SESSION.get")
def test_fetch_price_uses_id_in_url(mock_get):
    mock_get.return_value = _mock_response(
        {
            "success": True,
            "median_price": "6,50 €",
            "lowest_price": "6,00 €",
            "volume": "1,234",
        }
    )

    result = fetch_price("Chroma Case", "G18DD1F3004")

    assert result["name"] == "Chroma Case"
    assert result["id"] == "G18DD1F3004"
    url = mock_get.call_args.args[0]
    assert url.endswith("market_hash_name=G18DD1F3004")


@patch("fetch_prices.SESSION.get")
def test_fetch_price_normalizes_dash_cents(mock_get):
    mock_get.return_value = _mock_response(
        {
            "success": True,
            "median_price": "6,-- €",
            "lowest_price": "5,-- €",
            "volume": "100",
        }
    )

    result = fetch_price("Chroma Case")

    assert result["median_price"] == "6,00 €"
    assert result["lowest_price"] == "5,00 €"


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.SESSION.get")
def test_fetch_price_retries_on_success_false(mock_get, mock_sleep):
    mock_get.side_effect = [
        _mock_response({"success": False}),
        _mock_response({"success": False}),
        _mock_response(
            {
                "success": True,
                "median_price": "6,50 €",
                "lowest_price": "6,00 €",
                "volume": "10",
            }
        ),
    ]

    result = fetch_price("Chroma Case")

    assert result["median_price"] == "6,50 €"
    assert mock_get.call_count == 3


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.SESSION.get")
def test_fetch_price_retries_on_exception(mock_get, mock_sleep):
    mock_get.side_effect = [
        Exception("timeout"),
        Exception("timeout"),
        _mock_response(
            {
                "success": True,
                "median_price": "6,50 €",
                "lowest_price": "6,00 €",
                "volume": "10",
            }
        ),
    ]

    result = fetch_price("Chroma Case")

    assert result["median_price"] == "6,50 €"
    assert mock_get.call_count == 3


def _mock_429() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 429
    resp.raise_for_status.side_effect = requests.HTTPError("429 Too Many Requests")
    return resp


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.SESSION.get")
def test_fetch_price_all_429_raises_rate_limited(mock_get, mock_sleep):
    mock_get.return_value = _mock_429()

    with pytest.raises(RateLimited):
        fetch_price("Chroma Case")

    assert mock_get.call_count == 3


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.SESSION.get")
def test_fetch_price_429_then_success_does_not_raise(mock_get, mock_sleep):
    mock_get.side_effect = [
        _mock_429(),
        _mock_response(
            {
                "success": True,
                "median_price": "6,50 €",
                "lowest_price": "6,00 €",
                "volume": "10",
            }
        ),
    ]

    result = fetch_price("Chroma Case")

    assert result["median_price"] == "6,50 €"


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.SESSION.get")
def test_fetch_price_exhausted_retries_returns_none(mock_get, mock_sleep):
    mock_get.side_effect = Exception("timeout")

    result = fetch_price("Chroma Case", "G18DD1F3004")

    assert result == {
        "name": "Chroma Case",
        "id": "G18DD1F3004",
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }
    assert mock_get.call_count == 3


# --- main ---


_TEST_ITEMS = [
    {"name": "Chroma Case", "id": "G18DD1F3004", "type": "case"},
    {"name": "Chroma 2 Case", "id": "G18F91F3004", "type": "case"},
]


def _null_price(name: str = "x") -> dict:
    return {
        "name": name,
        "id": None,
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_writes_prices_json(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    mock_fetch_price.return_value = {
        "name": "Chroma Case",
        "id": "G18DD1F3004",
        "median_price": "6,50 €",
        "lowest_price": "6,00 €",
        "volume": "100",
    }

    main()

    output = json.loads(Path("prices.json").read_text())
    assert "updated_at" in output
    assert len(output["prices"]) == len(_TEST_ITEMS)
    assert output["prices"][0]["name"] == "Chroma Case"
    assert output["prices"][0]["id"] == "G18DD1F3004"
    # every fetched entry carries its own freshness timestamp
    assert output["prices"][0]["updated_at"] == output["updated_at"]


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_fetches_by_id(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    mock_fetch_price.return_value = _null_price()

    main()

    assert mock_fetch_price.call_args_list[0].args == ("Chroma Case", "G18DD1F3004")
    assert mock_fetch_price.call_args_list[1].args == ("Chroma 2 Case", "G18F91F3004")


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_slice_fetches_only_stride(
    mock_fetch_price, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLICE_COUNT", "2")
    monkeypatch.setenv("SLICE_INDEX", "1")
    items = [
        {"name": "A", "id": "G0", "type": "case"},
        {"name": "B", "id": "G1", "type": "case"},
        {"name": "C", "id": "G2", "type": "case"},
        {"name": "D", "id": "G3", "type": "case"},
    ]
    _write_items(tmp_path / "items.json", items)
    mock_fetch_price.side_effect = lambda name, item_id: _null_price(name)

    main()

    # stride index 1 of 2 → items B and D only
    assert [c.args[0] for c in mock_fetch_price.call_args_list] == ["B", "D"]
    # but the snapshot still lists all four items
    output = json.loads(Path("prices.json").read_text())
    assert [e["name"] for e in output["prices"]] == ["A", "B", "C", "D"]


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_merge_carries_over_unfetched(
    mock_fetch_price, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLICE_COUNT", "2")
    monkeypatch.setenv("SLICE_INDEX", "0")
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    # prior snapshot holds a real price for the item NOT in this slice
    Path("prices.json").write_text(
        json.dumps(
            {
                "updated_at": "2020-01-01T00:00:00+00:00",
                "prices": [
                    {
                        "name": "Chroma 2 Case",
                        "id": "G18F91F3004",
                        "median_price": "9,99 €",
                        "lowest_price": "9,90 €",
                        "volume": "42",
                        "updated_at": "2020-01-01T00:00:00+00:00",
                    }
                ],
            }
        )
    )
    mock_fetch_price.return_value = {
        "name": "Chroma Case",
        "id": "G18DD1F3004",
        "median_price": "6,50 €",
        "lowest_price": "6,00 €",
        "volume": "100",
    }

    main()

    output = json.loads(Path("prices.json").read_text())
    prices = {e["name"]: e for e in output["prices"]}
    # slice 0 → only Chroma Case fetched
    assert [c.args[0] for c in mock_fetch_price.call_args_list] == ["Chroma Case"]
    assert prices["Chroma Case"]["median_price"] == "6,50 €"
    # Chroma 2 Case carried over verbatim, old timestamp intact
    assert prices["Chroma 2 Case"]["median_price"] == "9,99 €"
    assert prices["Chroma 2 Case"]["updated_at"] == "2020-01-01T00:00:00+00:00"


def _seed_prices(entries: list[dict]) -> None:
    Path("prices.json").write_text(
        json.dumps({"updated_at": "2020-01-01T00:00:00+00:00", "prices": entries})
    )


_GOOD_PRIOR = {
    "name": "Chroma Case",
    "id": "G18DD1F3004",
    "median_price": "9,99 €",
    "lowest_price": "9,90 €",
    "volume": "42",
    "updated_at": "2020-01-01T00:00:00+00:00",
}


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_failed_fetch_keeps_last_known_price(
    mock_fetch_price, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    _seed_prices([_GOOD_PRIOR])
    # fetch "succeeds" but yields no price (429-exhausted or no listings)
    mock_fetch_price.return_value = _null_price("Chroma Case")

    main()

    prices = {
        e["name"]: e for e in json.loads(Path("prices.json").read_text())["prices"]
    }
    # the good prior price must survive, timestamp untouched
    assert prices["Chroma Case"] == _GOOD_PRIOR


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_aborts_and_exits_when_rate_limited(
    mock_fetch_price, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    _seed_prices([_GOOD_PRIOR])
    mock_fetch_price.side_effect = RateLimited("Chroma Case")

    with pytest.raises(SystemExit):
        main()

    # stopped after the first blocked item instead of grinding the rest
    assert mock_fetch_price.call_count == 1
    # snapshot still written, prior prices preserved
    prices = {
        e["name"]: e for e in json.loads(Path("prices.json").read_text())["prices"]
    }
    assert prices["Chroma Case"] == _GOOD_PRIOR


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_placeholder_for_never_fetched(
    mock_fetch_price, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLICE_COUNT", "2")
    monkeypatch.setenv("SLICE_INDEX", "0")
    _write_items(tmp_path / "items.json", _TEST_ITEMS)  # no existing prices.json
    mock_fetch_price.return_value = _null_price("Chroma Case")

    main()

    output = json.loads(Path("prices.json").read_text())
    prices = {e["name"]: e for e in output["prices"]}
    # unfetched item gets a null placeholder carrying its id, no timestamp
    assert prices["Chroma 2 Case"] == {
        "name": "Chroma 2 Case",
        "id": "G18F91F3004",
        "median_price": None,
        "lowest_price": None,
        "volume": None,
        "updated_at": None,
    }


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_fetches_skins_by_name(
    mock_fetch_price, mock_sleep, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_items(
        tmp_path / "items.json",
        [
            {
                "name": "MP5-SD | Acid Wash (Battle-Scarred)",
                "id": "G1817",
                "type": "skin",
            },
            {
                "name": "Negev | Infrastructure (Factory New)",
                "id": "G181C",
                "type": "skin",
            },
            {"name": "Chroma Case", "id": "G18DD1F3004", "type": "case"},
        ],
    )
    mock_fetch_price.return_value = {
        "name": "x",
        "id": None,
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }

    main()

    calls = [c.args for c in mock_fetch_price.call_args_list]
    assert calls == [
        ("MP5-SD | Acid Wash (Battle-Scarred)", None),
        ("Negev | Infrastructure (Factory New)", None),
        ("Chroma Case", "G18DD1F3004"),
    ]


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_sleeps_between_items(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    mock_fetch_price.return_value = _null_price()

    main()

    from fetch_prices import DELAY_SEC

    # full run (no slice env) → one sleep between each fetched item
    assert mock_sleep.call_count == len(_TEST_ITEMS) - 1
    mock_sleep.assert_called_with(DELAY_SEC)
    mock_sleep.assert_called_with(DELAY_SEC)
