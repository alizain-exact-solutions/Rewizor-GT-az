"""Pydantic request/response models for the public HTTP API.

These are the payloads the frontend exchanges with the service. Keep them
**flat and frontend-friendly** — the EPP-specific internal schemas live
under :mod:`src.epp.schemas` and are not exposed over the wire.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Accounting settings ────────────────────────────────────────────────────

class AccountingSettingsBase(BaseModel):
    """Sender / accounting details editable from the frontend.

    Maps to the ``accounting_settings`` table. The values feed the EPP
    [INFO] section (fields 4-14, 19, 21-24) and the [NAGLOWEK] place of
    issue (field 21), so the frontend form must cover everything an
    accountant needs to configure once per business.
    """

    # Identity — the sender company that owns the Rewizor GT license
    company_name: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Full legal company name (e.g. 'Exact Solution Electronics Sp. z o.o.').",
        examples=["Exact Solution Electronics Sp. z o.o."],
    )
    company_nip: str = Field(
        ...,
        min_length=8,
        max_length=13,
        description=(
            "Polish NIP (10 digits, no 'PL' prefix). The API strips a "
            "leading 'PL' automatically if the frontend sends one."
        ),
        examples=["5252704499"],
    )
    company_country_code: str = Field(
        "PL",
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code.",
        examples=["PL"],
    )
    company_street: Optional[str] = Field(
        None, max_length=50, examples=["Stanisława Bodycha 87"]
    )
    company_city: Optional[str] = Field(
        None, max_length=30, examples=["Reguły"]
    )
    company_postal_code: Optional[str] = Field(
        None, max_length=6, examples=["05-816"]
    )

    # Subiekt GT branch identifiers (optional — cosmetic in the [INFO] line)
    sender_id_code: Optional[str] = Field(
        None, max_length=20, description="INFO field 5.", examples=["Exact"]
    )
    sender_short_name: Optional[str] = Field(
        None, max_length=20, description="INFO field 6.", examples=["najnowszy"]
    )

    # Program / warehouse / operator (server defaults if omitted)
    producing_program: Optional[str] = Field(
        "Subiekt GT", max_length=255, description="INFO field 4."
    )
    warehouse_code: Optional[str] = Field("MAG", max_length=4)
    warehouse_name: Optional[str] = Field("Główny", max_length=40)
    warehouse_description: Optional[str] = Field(
        "Magazyn główny", max_length=255
    )
    operator_name: Optional[str] = Field("Szef", max_length=50)

    # Mapper default — EPP_DEFAULT_PAYMENT_TERM_DAYS replacement
    default_payment_term_days: int = Field(
        14,
        ge=0,
        le=365,
        description=(
            "Fallback payment term when OCR cannot extract a due date. "
            "Set to 0 to leave NAGLOWEK field 35 empty instead."
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


class AccountingSettingsCreate(AccountingSettingsBase):
    """Payload for PUT /accounting/settings — same shape as the base model."""
    pass


class AccountingSettingsResponse(AccountingSettingsBase):
    """Response body for GET/PUT /accounting/settings."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Documents ──────────────────────────────────────────────────────────────

class VatLine(BaseModel):
    """Per-rate VAT breakdown row stored alongside each document."""

    model_config = ConfigDict(from_attributes=True)

    line_no: int = Field(..., description="1-based ordinal within the document.")
    vat_symbol: str = Field(
        ...,
        description='Rewizor VAT symbol — "23"/"8"/"5"/"0"/"zw"/"oo"/...',
        examples=["23"],
    )
    vat_rate: Decimal = Field(..., examples=[Decimal("23.0000")])
    net_amount: Decimal = Field(default=Decimal("0"))
    vat_amount: Decimal = Field(default=Decimal("0"))
    gross_amount: Decimal = Field(default=Decimal("0"))


class DocumentSummary(BaseModel):
    """Lightweight document row returned by the listing endpoint.

    Excludes the per-rate VAT breakdown to keep listings cheap. Use
    :class:`DocumentDetail` (returned by ``GET /documents/{id}``) for
    the full record.
    """

    model_config = ConfigDict(from_attributes=True)

    document_id: int
    tenant_id: str
    invoice_number: Optional[str] = None
    doc_type: str = "FZ"
    status: str = "PENDING"
    is_correction: Optional[bool] = False
    issue_date: Optional[date] = None
    sale_date: Optional[date] = None
    receipt_date: Optional[date] = None
    payment_due_date: Optional[date] = None
    currency: str = "PLN"
    exchange_rate: Optional[Decimal] = None
    net_amount: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    gross_amount: Optional[Decimal] = None
    amount_paid: Optional[Decimal] = None
    payment_method: Optional[str] = None
    vendor: Optional[str] = None
    customer: Optional[str] = None
    contractor_nip: Optional[str] = None
    contractor_name: Optional[str] = None
    contractor_country: Optional[str] = None
    supplier_region: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DocumentDetail(DocumentSummary):
    """Full document record including the per-rate VAT breakdown."""

    corrected_doc_number: Optional[str] = None
    corrected_doc_date: Optional[date] = None
    contractor_street: Optional[str] = None
    contractor_city: Optional[str] = None
    contractor_postal_code: Optional[str] = None
    contractor_region: Optional[str] = None
    customer_nip: Optional[str] = None
    transaction_id: Optional[str] = None
    notes: Optional[str] = None
    supplier_country_code: Optional[str] = None
    vat_breakdown: List[VatLine] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """Paginated listing payload for ``GET /documents``."""

    items: List[DocumentSummary]
    total: int = Field(..., description="Total documents matching the filters.")
    limit: int
    offset: int


# ── EPP exports ────────────────────────────────────────────────────────────

class ExportSummary(BaseModel):
    """Metadata for a stored EPP export (no bytes)."""

    model_config = ConfigDict(from_attributes=True)

    export_id: int
    tenant_id: str
    filename: str
    file_size: int
    sha256: str
    epp_version: Optional[str] = None
    doc_count: int = 1
    export_kind: str = "single"
    document_ids: List[int] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class ExportListResponse(BaseModel):
    """Paginated listing payload for ``GET /exports``."""

    items: List[ExportSummary]
    total: int
    limit: int
    offset: int
