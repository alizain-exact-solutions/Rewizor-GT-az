"""Build the EPP [INFO] header from a business_details row.

The row comes from the ``business_details`` singleton table (see
:mod:`src.repositories.business_repo`) managed through the
``/api/v1/business-details`` endpoints.
"""

from typing import Any, Dict, Optional

from src.epp.schemas import EPPInfo


class BusinessDetailsNotConfigured(Exception):
    """Raised when no row exists in ``business_details`` yet.

    The API layer translates this to HTTP 412 so the frontend can prompt
    the user to fill in the Business Details form before running an EPP
    export.
    """


def _normalise_nip(value: str) -> str:
    nip = (value or "").strip().upper().replace(" ", "").replace("-", "")
    if nip.startswith("PL") and nip[2:].isdigit():
        nip = nip[2:]
    return nip


def build_epp_info(row: Dict[str, Any]) -> EPPInfo:
    """Construct the EPP [INFO] header from a business_details row."""
    nip = _normalise_nip(row.get("company_nip") or "")
    country = (row.get("company_country_code") or "PL").strip().upper()

    return EPPInfo(
        producing_program=row.get("producing_program") or "Subiekt GT",
        sender_id_code=row.get("sender_id_code") or "",
        sender_short_name=row.get("sender_short_name") or "",
        sender_long_name=row.get("company_name") or "",
        sender_city=row.get("company_city") or "",
        sender_postal_code=row.get("company_postal_code") or "",
        sender_street=row.get("company_street") or "",
        sender_nip=nip,
        warehouse_code=row.get("warehouse_code") or "MAG",
        warehouse_name=row.get("warehouse_name") or "Główny",
        warehouse_description=row.get("warehouse_description") or "Magazyn główny",
        operator_name=row.get("operator_name") or "Szef",
        country_prefix=country,
        eu_vat_number=nip,
        is_sender_eu=0,
    )


def get_payment_term_days(row: Dict[str, Any]) -> Optional[int]:
    days = row.get("default_payment_term_days")
    try:
        return int(days) if days is not None else None
    except (TypeError, ValueError):
        return None
