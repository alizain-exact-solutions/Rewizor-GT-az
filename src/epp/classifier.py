"""
Supplier origin classifier for Rewizor GT EDI++ export.

Classifies suppliers as PL / EU / NON_EU using a layered strategy:
  1. VAT/NIP prefix  (strongest signal)
  2. ISO country code
  3. Country name text matching  (handles messy OCR text)
  4. Currency fallback

Used by the mapper to determine VAT symbol, transaction code,
and payment method handling.
"""

from typing import Any, Dict, Optional

from src.epp.constants import EU_COUNTRIES, EU_MEMBER_STATES, NON_EU_COUNTRIES

# Pre-built lookup: lowercase name → (type, code)
_NAME_LOOKUP: dict[str, tuple[str, str]] = {}
for _c in EU_COUNTRIES:
    for _name in _c["names"]:
        _NAME_LOOKUP[_name] = ("EU", _c["code"])
for _c in NON_EU_COUNTRIES:
    for _name in _c["names"]:
        _NAME_LOOKUP[_name] = ("NON_EU", _c["code"])


def _detect_from_vat_prefix(nip: str) -> Optional[Dict[str, Any]]:
    """Extract origin from the 2-letter prefix of a VAT / NIP number.

    EU VAT numbers always start with the country's ISO code (e.g. DE, FR).
    This is the strongest signal — more reliable than free-text country.
    """
    if not nip or len(nip) < 3:
        return None

    prefix = nip[:2].upper()

    # Only trigger if prefix looks like letters (not digits)
    if not prefix.isalpha():
        return None

    if prefix == "PL":
        return {"type": "PL", "code": "PL"}
    if prefix in EU_MEMBER_STATES:
        return {"type": "EU", "code": prefix}
    # GB, US, etc. — any known non-EU prefix
    return {"type": "NON_EU", "code": prefix}


def _detect_from_country_code(country: str) -> Optional[Dict[str, Any]]:
    """Classify from an ISO 3166-1 alpha-2 country code.

    Only triggers on exactly 2-letter strings.  Longer text (e.g.
    "United States", "Holland") falls through to text matching.
    """
    code = country.strip().upper()
    if not code or len(code) != 2 or not code.isalpha():
        return None

    if code == "PL":
        return {"type": "PL", "code": "PL"}
    if code in EU_MEMBER_STATES:
        return {"type": "EU", "code": code}
    # Any other 2-letter code → NON_EU
    return {"type": "NON_EU", "code": code}


def _detect_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Fuzzy match country names in free-text (address, country field).

    Scans for known EU names first, then NON-EU.  Returns the first match.
    """
    normalised = text.lower().strip()
    if not normalised:
        return None

    # Check against pre-built lookup — longest names first for accuracy
    for name in sorted(_NAME_LOOKUP, key=len, reverse=True):
        if name in normalised:
            origin_type, code = _NAME_LOOKUP[name]
            if code == "PL":
                return {"type": "PL", "code": "PL"}
            return {"type": origin_type, "code": code}

    return None


def classify_supplier(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a supplier as PL / EU / NON_EU.

    Strategy (in priority order):
      1. VAT/NIP prefix  — e.g. "DE298765432" → EU/DE
      2. ``contractor_country`` as ISO code — e.g. "US" → NON_EU
      3. Country + address text matching — e.g. "Mountain View, CA, United States" → NON_EU
      4. Currency fallback — PLN → PL, anything else → NON_EU

    Returns::

        {"type": "PL" | "EU" | "NON_EU", "code": "XX" | None}
    """
    # 1. VAT prefix (strongest)
    nip = invoice.get("contractor_nip") or invoice.get("nip") or ""
    vat_result = _detect_from_vat_prefix(nip)
    if vat_result:
        return vat_result

    # 2. ISO country code
    country = invoice.get("contractor_country") or ""
    code_result = _detect_from_country_code(country)
    if code_result:
        return code_result

    # 3. Free-text matching on country + address + city
    text_parts = [
        invoice.get("contractor_country") or "",
        invoice.get("contractor_city") or "",
        invoice.get("contractor_street") or "",
    ]
    combined_text = " ".join(text_parts)
    text_result = _detect_from_text(combined_text)
    if text_result:
        return text_result

    # 4. Currency fallback
    currency = (invoice.get("currency") or "PLN").strip().upper()
    if currency == "PLN":
        return {"type": "PL", "code": "PL"}

    # 5. Polish NIP format (10 digits, no prefix)
    digits = "".join(c for c in nip if c.isdigit())
    if digits and len(digits) == 10:
        return {"type": "PL", "code": "PL"}

    return {"type": "NON_EU", "code": None}
