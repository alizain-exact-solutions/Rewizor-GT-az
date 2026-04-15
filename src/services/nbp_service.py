"""
NBP (National Bank of Poland) exchange rate service.

Fetches mid exchange rates from api.nbp.pl Table A for converting
foreign-currency invoice amounts to PLN.  Used by the Rewizor
mapping pipeline when the OCR doesn't provide a reliable rate.

NBP publishes rates on business days only.  When the exact invoice
date falls on a weekend or holiday, we look up the *previous*
business day's rate — which is the standard Polish accounting rule
("kurs średni NBP z ostatniego dnia roboczego poprzedzającego dzień
poniesienia kosztu / uzyskania przychodu").

The service includes a simple in-memory cache keyed by (currency, date)
so repeated calls for the same invoice date don't hit the API.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_NBP_BASE = "https://api.nbp.pl/api/exchangerates/rates/a"

# In-memory cache: (currency_upper, date_str) → mid rate
_cache: dict[tuple[str, str], float] = {}


def get_nbp_rate(currency: str, invoice_date: str) -> Optional[float]:
    """Fetch the NBP Table A mid rate for *currency* on *invoice_date*.

    Parameters
    ----------
    currency : str
        ISO 4217 code, e.g. ``"USD"``, ``"EUR"``.  ``"PLN"`` returns
        ``1.0`` immediately without hitting the API.
    invoice_date : str
        ISO date ``YYYY-MM-DD``.

    Returns
    -------
    float | None
        The mid exchange rate, or ``None`` if the lookup failed
        (unknown currency, API down, date too old, etc.).
    """
    code = currency.strip().upper()
    if code == "PLN":
        return 1.0

    date_str = invoice_date.strip()
    if not date_str:
        return None

    cache_key = (code, date_str)
    if cache_key in _cache:
        return _cache[cache_key]

    rate = _fetch_rate(code, date_str)
    if rate is not None:
        _cache[cache_key] = rate
    return rate


def _fetch_rate(code: str, date_str: str) -> Optional[float]:
    """Try the exact date first, then walk backwards up to 7 days."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning("NBP: invalid date format %r", date_str)
        return None

    # Try exact date, then go back up to 7 calendar days
    # (covers weekends + typical Polish public holidays)
    for delta in range(8):
        attempt = (dt - timedelta(days=delta)).strftime("%Y-%m-%d")
        rate = _call_nbp_api(code, attempt)
        if rate is not None:
            return rate

    logger.warning(
        "NBP: no rate found for %s on %s (tried 8 days back)", code, date_str
    )
    return None


def _call_nbp_api(code: str, date_str: str) -> Optional[float]:
    """Single HTTP call to NBP API. Returns mid rate or None on 404/error."""
    url = f"{_NBP_BASE}/{code.lower()}/{date_str}/"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers={"Accept": "application/json"})

        if resp.status_code == 404:
            # No data for this date (weekend/holiday) — caller will retry
            return None

        if resp.status_code != 200:
            logger.warning("NBP API %s returned %d", url, resp.status_code)
            return None

        data = resp.json()
        mid = data["rates"][0]["mid"]
        return round(float(mid), 4)

    except httpx.TimeoutException:
        logger.warning("NBP API timeout for %s %s", code, date_str)
        return None
    except Exception as exc:
        logger.warning("NBP API error for %s %s: %s", code, date_str, exc)
        return None


def clear_cache() -> None:
    """Clear the rate cache (useful for testing)."""
    _cache.clear()
