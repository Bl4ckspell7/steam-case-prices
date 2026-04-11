# steam-prices

[![Test](https://github.com/Bl4ckspell7/steam-prices/actions/workflows/test.yml/badge.svg)](https://github.com/Bl4ckspell7/steam-prices/actions/workflows/test.yml)
[![Last fetch](https://img.shields.io/github/last-commit/Bl4ckspell7/steam-prices/data?label=last%20fetch)](https://github.com/Bl4ckspell7/steam-prices/tree/data)

Fetches CS2 case prices from the Steam Community Market and saves them to `prices.json`.

## Setup

```
uv sync
```

## Usage

```
uv run fetch_prices.py
```

Outputs `prices.json` with median/lowest prices and volume for each item.

## Output format

```json
{
  "updated_at": "2026-03-15T12:00:00+00:00",
  "prices": [
    {
      "name": "Chroma Case",
      "median_price": "0,03€",
      "lowest_price": "0,03€",
      "volume": "12345"
    }
  ]
}
```

## Development

```bash
# unit tests
uv run pytest

# unit + integration tests (live Steam API request)
uv run pytest -m integration

# lint
uv run ruff check

# lint + autofix
uv run ruff check --fix

# format check
uv run ruff format --check

# format
uv run ruff format
```
