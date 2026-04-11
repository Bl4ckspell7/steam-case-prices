import json
import re
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from fetch_prices import _normalize_price, fetch_price, main


# --- integration ---


_PRICE_RE = re.compile(r"^\d+,\d{2}\s*€$")


@pytest.mark.integration
def test_fetch_price_real_request():
    result = fetch_price("Chroma Case")

    assert result["name"] == "Chroma Case"
    assert result["median_price"] is not None or result["lowest_price"] is not None

    for field in ("median_price", "lowest_price"):
        value = result[field]
        if value is not None:
            assert _PRICE_RE.match(value), f"{field} has unexpected format: {value!r}"

    assert result["volume"] is not None
    assert result["volume"].replace(",", "").isdigit(), f"volume has unexpected format: {result['volume']!r}"


# --- _normalize_price ---


def test_normalize_price_dash_cents():
    assert _normalize_price("6,-- €") == "6,00 €"


def test_normalize_price_normal():
    assert _normalize_price("6,50 €") == "6,50 €"


def test_normalize_price_none():
    assert _normalize_price(None) is None


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
        "median_price": "6,50 €",
        "lowest_price": "6,00 €",
        "volume": "1,234",
    }


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

    result = fetch_price("Chroma Case")

    assert result == {
        "name": "Chroma Case",
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }
    assert mock_get.call_count == 3


# --- main ---


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_writes_prices_json(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_fetch_price.return_value = {
        "name": "Chroma Case",
        "median_price": "6,50 €",
        "lowest_price": "6,00 €",
        "volume": "100",
    }

    main()

    output = json.loads(Path("prices.json").read_text())
    assert "updated_at" in output
    assert len(output["prices"]) > 0
    assert output["prices"][0]["name"] == "Chroma Case"


@patch("fetch_prices.time.sleep")
@patch("fetch_prices.fetch_price")
def test_main_sleeps_between_items(mock_fetch_price, mock_sleep, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_fetch_price.return_value = {
        "name": "x",
        "median_price": None,
        "lowest_price": None,
        "volume": None,
    }

    main()

    from fetch_prices import DELAY_SEC, ITEMS

    assert mock_sleep.call_count == len(ITEMS) - 1
    mock_sleep.assert_called_with(DELAY_SEC)
