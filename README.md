# steam-prices

[![Test](https://github.com/Bl4ckspell7/steam-prices/actions/workflows/test.yml/badge.svg)](https://github.com/Bl4ckspell7/steam-prices/actions/workflows/test.yml)
[![Last fetch](https://img.shields.io/github/last-commit/Bl4ckspell7/steam-prices/data?label=last%20fetch)](https://github.com/Bl4ckspell7/steam-prices/tree/data)

Fetches CS2 case prices from the Steam Community Market and saves them to `prices.json`.

## Usage

```
uv run fetch_prices.py
```

Outputs `prices.json` with median/lowest prices and volume for each item.

Items are configured in `items.json`. To add one, append `{ "name": "...", "id": null, "type": "..." }` — the script resolves the market ID automatically on the next run.

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

## Upgrading dependencies

Remove and re-add to bump the version floors in `pyproject.toml`:

```bash
uv remove requests && uv add requests
uv remove --dev pytest ruff && uv add --dev pytest ruff
```
