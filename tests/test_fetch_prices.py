import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fetch_prices import (
    _normalize_price,
    fetch_price,
    main,
    resolve_id,
    resolve_missing_ids,
)


# --- integration ---


_PRICE_RE = re.compile(r"^\d+,\d{2}\s*€$")


def _assert_valid_prices(result: dict) -> None:
    assert result["median_price"] is not None or result["lowest_price"] is not None

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
    result = fetch_price("Chroma Case")

    assert result["name"] == "Chroma Case"
    _assert_valid_prices(result)


@pytest.mark.integration
def test_fetch_price_by_id_real_request():
    result = fetch_price("Chroma Case", "G18DD1F3004")

    assert result["name"] == "Chroma Case"
    assert result["id"] == "G18DD1F3004"
    _assert_valid_prices(result)


@pytest.mark.integration
def test_resolve_id_real_request():
    assert resolve_id("Chroma Case") == "G18DD1F3004"


# --- _normalize_price ---


def test_normalize_price_dash_cents():
    assert _normalize_price("6,-- €") == "6,00 €"


def test_normalize_price_normal():
    assert _normalize_price("6,50 €") == "6,50 €"


def test_normalize_price_none():
    assert _normalize_price(None) is None


# --- resolve_id ---


def _mock_redirect(location: str | None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 302 if location else 200
    resp.headers = {"Location": location} if location else {}
    return resp


@patch("fetch_prices.requests.get")
def test_resolve_id_parses_redirect(mock_get):
    mock_get.return_value = _mock_redirect(
        "https://steamcommunity.com/market/listings/730/G18F91F3004"
    )

    assert resolve_id("Chroma 2 Case") == "G18F91F3004"
    assert mock_get.call_args.kwargs["allow_redirects"] is False


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.requests.get")
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


@patch("fetch_prices.requests.get")
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


@patch("fetch_prices.requests.get")
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


@patch("fetch_prices.requests.get")
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
@patch("fetch_prices.requests.get")
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
@patch("fetch_prices.requests.get")
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


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.requests.get")
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


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_fetches_by_id(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    mock_fetch_price.return_value = {
        "name": "x",
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }

    main()

    assert mock_fetch_price.call_args_list[0].args == ("Chroma Case", "G18DD1F3004")
    assert mock_fetch_price.call_args_list[1].args == ("Chroma 2 Case", "G18F91F3004")


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_sleeps_between_items(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_items(tmp_path / "items.json", _TEST_ITEMS)
    mock_fetch_price.return_value = {
        "name": "x",
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }

    main()

    from fetch_prices import DELAY_SEC

    assert mock_sleep.call_count == len(_TEST_ITEMS) - 1
    mock_sleep.assert_called_with(DELAY_SEC)
