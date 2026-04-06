"""
Pydantic models for Rewizor GT EDI++ (EPP) file sections.

Field ordering matches the InsERT EDI++ 1.12 specification tables:
  * ``EPPInfo``    – [INFO]       section (Table 2, ~19 fields)
  * ``EPPHeader``  – [NAGLOWEK]   section (Table 3, ~51 fields)
  * ``EPPVatRow``  – [ZAWARTOSC]  section (Table 4/5, 5 fields)
"""

from typing import List, Optional

from pydantic import BaseModel, field_validator

from src.epp.constants import (
    DOC_TYPE_PURCHASE_INVOICE,
    EPP_ENCODING_WIN1250,
    EPP_PURPOSE_ACCOUNTING_OFFICE,
    EPP_VERSION,
    PAYMENT_TRANSFER,
    REGISTER_PURCHASE,
    VALID_DOC_TYPES,
    VALID_VAT_SYMBOLS,
)


# ── Table 2: [INFO] ─────────────────────────────────────────────────────────

class EPPInfo(BaseModel):
    """Global file header – one per EPP file.

    Fields 1-19 per EDI++ Table 2.
    """

    version: str = EPP_VERSION                  # 1  Wersja
    purpose: int = EPP_PURPOSE_ACCOUNTING_OFFICE # 2  Cel
    encoding: str = EPP_ENCODING_WIN1250        # 3  Kodowanie
    generator_name: str = "ExactFlow Finance"   # 4  Nazwa programu
    generator_nip: str = ""                     # 5  NIP programu  (unused – "")
    generator_city: str = ""                    # 6  Miejscowość   (unused – "")
    company_name: str = ""                      # 7  Nazwa firmy
    company_street: str = ""                    # 8  Ulica
    company_city: str = ""                      # 9  Miasto
    company_postal_code: str = ""               # 10 Kod pocztowy
    company_nip: str = ""                       # 11 NIP firmy (with country prefix e.g. "PL5252704499")
    # Fields 12-19 are reserved / unused – emitted as empty commas


# ── Table 3: [NAGLOWEK] ─────────────────────────────────────────────────────

class EPPHeader(BaseModel):
    """Single document header – full Table 3 (~51 fields)."""

    @field_validator("doc_type")
    @classmethod
    def validate_doc_type(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in VALID_DOC_TYPES:
            raise ValueError(f"Invalid doc_type '{v}'. Must be one of: {sorted(VALID_DOC_TYPES)}")
        return v

    @field_validator("issue_date")
    @classmethod
    def validate_issue_date(cls, v: str) -> str:
        if not v:
            raise ValueError("issue_date is required")
        return v

    # ── Document identification ──
    doc_type: str = DOC_TYPE_PURCHASE_INVOICE   # 1  Typ
    lp_dekretacji: int = 1                      # 2  Lp dekretacji
    rodzaj_dokumentu: int = 0                   # 3  Rodzaj dok. (0=normal)
    rodzaj_rejestru: int = 1                    # 4  Rodzaj rejestru (1=purchase)
    numer_rejestru: str = ""                    # 5  Numer rejestru
    doc_number: str = ""                        # 6  Numer dokumentu
    numer_ewidencyjny: str = ""                 # 7  Numer ewidencyjny
    numer_oryginalny: str = ""                  # 8  Numer oryginalny
    kod_transakcji: str = ""                    # 9  Kod transakcji
    field_10: str = ""                          # 10 (reserved)

    # ── Contractor ──
    contractor_symbol: str = ""                 # 11 Symbol kontrahenta
    contractor_code: str = ""                   # 12 Kod kontrahenta
    contractor_name: str = ""                   # 13 Nazwa kontrahenta
    contractor_street: str = ""                 # 14 Ulica
    contractor_city: str = ""                   # 15 Miasto
    contractor_postal_code: str = ""            # 16 Kod pocztowy
    contractor_region: str = ""                 # 17 Województwo / region
    field_18: str = ""                          # 18 (reserved)
    contractor_country: str = ""                # 19 Kraj
    contractor_nip: str = ""                    # 20 NIP kontrahenta

    # ── Dates ──
    issue_date: str = ""                        # 21 Data wystawienia
    sale_date: Optional[str] = None             # 22 Data sprzedaży
    receipt_date: Optional[str] = None          # 23 Data wpływu

    # ── Flags ──
    flag_24: int = 1                            # 24 (flag)
    flag_25: int = 0                            # 25 (flag)

    # ── Amounts ──
    net_total: float = 0.0                      # 26 Netto
    vat_total: float = 0.0                      # 27 VAT
    gross_total: float = 0.0                    # 28 Brutto
    field_29: float = 0.0                       # 29 (optional amount)

    # ── Payment ──
    payment_method: str = ""                    # 30 Forma płatności (empty or code)
    amount_paid: float = 0.0                    # 31 Zapłacono
    field_32: str = ""                          # 32 (reserved)
    payment_due_date: Optional[str] = None      # 33 Termin płatności
    field_34: float = 0.0                       # 34 (optional amount)
    field_35: float = 0.0                       # 35 (optional – may duplicate gross)

    # ── Additional flags ──
    flag_36: int = 0                            # 36
    flag_37: int = 0                            # 37
    flag_38: int = 0                            # 38
    field_39: str = "0"                         # 39
    field_40: str = "0"                         # 40
    field_41: str = "0"                         # 41
    field_42: str = "0"                         # 42
    field_43: str = "0"                         # 43

    # ── Currency ──
    currency: str = "PLN"                       # 44 Waluta
    exchange_rate: float = 1.0                  # 45 Kurs waluty

    # ── Trailing ──
    field_46: str = "0"                         # 46
    field_47: str = "0"                         # 47
    field_48: str = "0"                         # 48
    flag_49: int = 0                            # 49
    flag_50: int = 0                            # 50
    flag_51: int = 1                            # 51


# ── Table 4/5: [ZAWARTOSC] ──────────────────────────────────────────────────

class EPPVatRow(BaseModel):
    """Single VAT-rate breakdown row – one per rate per invoice.

    For reverse charge ("00"), ``vat_rate`` must be ``-5.00``.
    """

    @field_validator("vat_symbol")
    @classmethod
    def validate_vat_symbol(cls, v: str) -> str:
        if v not in VALID_VAT_SYMBOLS:
            raise ValueError(f"Invalid vat_symbol '{v}'. Must be one of: {sorted(VALID_VAT_SYMBOLS)}")
        return v

    vat_symbol: str                     # "23", "8", "5", "0", "Zw", "00"
    vat_rate: float                     # e.g. 23.00 or -5.00 for reverse charge
    net_amount: float = 0.0
    vat_amount: float = 0.0
    gross_amount: float = 0.0


# ── Composite ────────────────────────────────────────────────────────────────

class EPPDocument(BaseModel):
    """One invoice with its VAT breakdown – used by the EPP writer."""

    header: EPPHeader
    vat_rows: List[EPPVatRow]
