"""Pydantic request/response models for the public HTTP API."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Business details (sender / accounting) ─────────────────────────────────

class BusinessDetailsBase(BaseModel):
    """Sender / accounting details that populate the EPP [INFO] section."""

    company_name: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Full legal company name.",
        examples=["Exact Solution Electronics Sp. z o.o."],
    )
    company_nip: str = Field(
        ...,
        min_length=8,
        max_length=13,
        description=(
            "Polish NIP (10 digits, no 'PL' prefix). A leading 'PL' is "
            "stripped automatically."
        ),
        examples=["5252704499"],
    )
    company_country_code: str = Field(
        "PL", min_length=2, max_length=2, examples=["PL"]
    )
    company_street: Optional[str] = Field(None, max_length=50)
    company_city: Optional[str] = Field(None, max_length=30)
    company_postal_code: Optional[str] = Field(None, max_length=6)

    sender_id_code: Optional[str] = Field(None, max_length=20)
    sender_short_name: Optional[str] = Field(None, max_length=20)

    producing_program: str = Field("Subiekt GT", max_length=255)
    warehouse_code: str = Field("MAG", max_length=4)
    warehouse_name: str = Field("Główny", max_length=40)
    warehouse_description: str = Field("Magazyn główny", max_length=255)
    operator_name: str = Field("Szef", max_length=50)

    default_payment_term_days: int = Field(
        14,
        ge=0,
        le=365,
        description=(
            "Fallback payment term in days when the OCR cannot extract a "
            "due date. Set to 0 to leave NAGLOWEK field 35 empty."
        ),
    )

    @field_validator("company_nip")
    @classmethod
    def _strip_pl_prefix(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "").replace("-", "")
        if v.startswith("PL") and v[2:].isdigit():
            v = v[2:]
        return v

    @field_validator("company_country_code")
    @classmethod
    def _uppercase_country(cls, v: str) -> str:
        return v.strip().upper()


class BusinessDetailsCreate(BusinessDetailsBase):
    """Payload for POST /business-details (create or replace)."""
    pass


class BusinessDetailsResponse(BusinessDetailsBase):
    """Response body for GET / POST /business-details."""

    model_config = ConfigDict(from_attributes=True)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── EPP exports ────────────────────────────────────────────────────────────

class ExportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_size: int
    sha256: str
    epp_version: Optional[str] = None
    invoice_number: Optional[str] = None
    doc_type: Optional[str] = None
    issue_date: Optional[date] = None
    currency: Optional[str] = None
    net_amount: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    gross_amount: Optional[Decimal] = None
    contractor_name: Optional[str] = None
    contractor_nip: Optional[str] = None
    created_at: Optional[datetime] = None


class ExportListResponse(BaseModel):
    items: List[ExportSummary]
    total: int = Field(..., description="Total number of stored exports.")
    limit: int
    offset: int
