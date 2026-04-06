"""
Rewizor GT EDI++ constants.

VAT symbols, document types, payment methods, and other
lookup values used throughout the EPP export pipeline.
"""

from typing import Any

# ---------------------------------------------------------------------------
# EDI++ file metadata
# ---------------------------------------------------------------------------
EPP_VERSION = "1.10"
EPP_PURPOSE_ACCOUNTING_OFFICE = 0
EPP_ENCODING_WIN1250 = "1250"

# ---------------------------------------------------------------------------
# Document types  (Table 3 – pole "Typ dokumentu")
# All 12 Rewizor GT EDI++ document types per InsERT spec.
# ---------------------------------------------------------------------------

# ── Invoices ──
DOC_TYPE_PURCHASE_INVOICE = "FZ"                # Faktura zakupu
DOC_TYPE_SALES_INVOICE = "FS"                   # Faktura sprzedaży

# ── Costs ──
DOC_TYPE_PURCHASE_COSTS = "KZ"                  # Koszty zakupu
DOC_TYPE_SALES_COSTS = "KS"                     # Koszty sprzedaży

# ── Corrections (korekty) ──
DOC_TYPE_PURCHASE_INVOICE_CORRECTION = "FZK"    # Korekta faktury zakupu
DOC_TYPE_SALES_INVOICE_CORRECTION = "FSK"       # Korekta faktury sprzedaży
DOC_TYPE_PURCHASE_COSTS_CORRECTION = "KZK"      # Korekta kosztów zakupu
DOC_TYPE_SALES_COSTS_CORRECTION = "KSK"         # Korekta kosztów sprzedaży

# ── Non-VAT documents ──
DOC_TYPE_BANK_STATEMENT = "WB"                  # Wyciąg bankowy
DOC_TYPE_CASH_REPORT = "RK"                     # Raport kasowy
DOC_TYPE_POSTING_ORDER = "PK"                   # Polecenie księgowania
DOC_TYPE_INTERNAL_DOCUMENT = "DE"               # Dowód wewnętrzny

VALID_DOC_TYPES = {
    DOC_TYPE_PURCHASE_INVOICE,
    DOC_TYPE_SALES_INVOICE,
    DOC_TYPE_PURCHASE_COSTS,
    DOC_TYPE_SALES_COSTS,
    DOC_TYPE_PURCHASE_INVOICE_CORRECTION,
    DOC_TYPE_SALES_INVOICE_CORRECTION,
    DOC_TYPE_PURCHASE_COSTS_CORRECTION,
    DOC_TYPE_SALES_COSTS_CORRECTION,
    DOC_TYPE_BANK_STATEMENT,
    DOC_TYPE_CASH_REPORT,
    DOC_TYPE_POSTING_ORDER,
    DOC_TYPE_INTERNAL_DOCUMENT,
}

# Correction types → amounts are negative (credit notes)
CORRECTION_DOC_TYPES = {
    DOC_TYPE_PURCHASE_INVOICE_CORRECTION,
    DOC_TYPE_SALES_INVOICE_CORRECTION,
    DOC_TYPE_PURCHASE_COSTS_CORRECTION,
    DOC_TYPE_SALES_COSTS_CORRECTION,
}

# ---------------------------------------------------------------------------
# Register types  (Table 3 – pole "Rodzaj rejestru")
# ---------------------------------------------------------------------------
REGISTER_PURCHASE = 1   # Rejestr zakupów
REGISTER_SALES = 2      # Rejestr sprzedaży
REGISTER_OTHER = 0      # Inne (WB, RK, PK, DE)

DOC_TYPE_TO_REGISTER: dict[str, int] = {
    DOC_TYPE_PURCHASE_INVOICE: REGISTER_PURCHASE,
    DOC_TYPE_SALES_INVOICE: REGISTER_SALES,
    DOC_TYPE_PURCHASE_COSTS: REGISTER_PURCHASE,
    DOC_TYPE_SALES_COSTS: REGISTER_SALES,
    DOC_TYPE_PURCHASE_INVOICE_CORRECTION: REGISTER_PURCHASE,
    DOC_TYPE_SALES_INVOICE_CORRECTION: REGISTER_SALES,
    DOC_TYPE_PURCHASE_COSTS_CORRECTION: REGISTER_PURCHASE,
    DOC_TYPE_SALES_COSTS_CORRECTION: REGISTER_SALES,
    DOC_TYPE_BANK_STATEMENT: REGISTER_OTHER,
    DOC_TYPE_CASH_REPORT: REGISTER_OTHER,
    DOC_TYPE_POSTING_ORDER: REGISTER_OTHER,
    DOC_TYPE_INTERNAL_DOCUMENT: REGISTER_OTHER,
}

# Non-VAT document types (no [ZAWARTOSC] VAT breakdown needed)
NON_VAT_DOC_TYPES = {
    DOC_TYPE_BANK_STATEMENT,
    DOC_TYPE_CASH_REPORT,
    DOC_TYPE_POSTING_ORDER,
    DOC_TYPE_INTERNAL_DOCUMENT,
}

# ---------------------------------------------------------------------------
# VAT symbols  (Table 4/5 – pole "Symbol stawki")
# ---------------------------------------------------------------------------
VAT_SYMBOL_23 = "23"
VAT_SYMBOL_8 = "8"
VAT_SYMBOL_5 = "5"
VAT_SYMBOL_0 = "0"
VAT_SYMBOL_EXEMPT = "zw"               # Zwolniony
VAT_SYMBOL_REVERSE_CHARGE = "oo"        # Odwrotne obciążenie (letter 'o', not zero)
VAT_SYMBOL_NOT_APPLICABLE = "np"        # Nie podlega

VALID_VAT_SYMBOLS = {
    VAT_SYMBOL_23,
    VAT_SYMBOL_8,
    VAT_SYMBOL_5,
    VAT_SYMBOL_0,
    "zw",
    "oo",
    VAT_SYMBOL_NOT_APPLICABLE,
}

# Map numeric VAT rates to their canonical symbol string
RATE_TO_SYMBOL: dict[float, str] = {
    23.0: VAT_SYMBOL_23,
    8.0: VAT_SYMBOL_8,
    5.0: VAT_SYMBOL_5,
    0.0: VAT_SYMBOL_0,
}

# Rewizor GT internal rate marker for reverse charge ("oo" symbol).
# The import engine uses -5.00 to distinguish it from the standard 0% rate.
VAT_RATE_REVERSE_CHARGE = -5.0

# Rate marker for exempt ("zw" symbol) – Polish domestic exempt transactions.
VAT_RATE_EXEMPT = -1.0

# Rate marker for "np" (nie podlega) – foreign services / import usług.
VAT_RATE_NOT_APPLICABLE = -1.0

# ---------------------------------------------------------------------------
# Payment methods  (Table 3 – pole "Forma płatności")
# ---------------------------------------------------------------------------
PAYMENT_TRANSFER = "P"      # Przelew
PAYMENT_CASH = "G"          # Gotówka
PAYMENT_CARD = "K"          # Karta
PAYMENT_COMPENSATION = "O"  # Kompensata

VALID_PAYMENT_METHODS = {
    PAYMENT_TRANSFER,
    PAYMENT_CASH,
    PAYMENT_CARD,
    PAYMENT_COMPENSATION,
}

# ---------------------------------------------------------------------------
# Country classification — EU vs NON-EU
# Used for VAT classification, JPK compliance, and transaction codes.
#
# Each entry maps an ISO 3166-1 alpha-2 code to lowercase name aliases
# that may appear in messy OCR / invoice text.
# ---------------------------------------------------------------------------

EU_COUNTRIES: list[dict[str, Any]] = [
    {"code": "AT", "names": ["austria"]},
    {"code": "BE", "names": ["belgium"]},
    {"code": "BG", "names": ["bulgaria"]},
    {"code": "HR", "names": ["croatia"]},
    {"code": "CY", "names": ["cyprus"]},
    {"code": "CZ", "names": ["czech republic", "czechia"]},
    {"code": "DK", "names": ["denmark"]},
    {"code": "EE", "names": ["estonia"]},
    {"code": "FI", "names": ["finland"]},
    {"code": "FR", "names": ["france"]},
    {"code": "DE", "names": ["germany"]},
    {"code": "GR", "names": ["greece"]},
    {"code": "HU", "names": ["hungary"]},
    {"code": "IE", "names": ["ireland"]},
    {"code": "IT", "names": ["italy"]},
    {"code": "LV", "names": ["latvia"]},
    {"code": "LT", "names": ["lithuania"]},
    {"code": "LU", "names": ["luxembourg"]},
    {"code": "MT", "names": ["malta"]},
    {"code": "NL", "names": ["netherlands", "holland"]},
    {"code": "PL", "names": ["poland", "polska"]},
    {"code": "PT", "names": ["portugal"]},
    {"code": "RO", "names": ["romania"]},
    {"code": "SK", "names": ["slovakia"]},
    {"code": "SI", "names": ["slovenia"]},
    {"code": "ES", "names": ["spain"]},
    {"code": "SE", "names": ["sweden"]},
]

# Derived set for fast ISO-code lookups
EU_MEMBER_STATES: set[str] = {c["code"] for c in EU_COUNTRIES}

NON_EU_COUNTRIES: list[dict[str, Any]] = [
    {"code": "US", "names": ["united states", "usa"]},
    {"code": "GB", "names": ["united kingdom", "uk", "great britain"]},
    {"code": "SG", "names": ["singapore"]},
    {"code": "CH", "names": ["switzerland"]},
    {"code": "NO", "names": ["norway"]},
    {"code": "AE", "names": ["uae", "united arab emirates"]},
    {"code": "IN", "names": ["india"]},
    {"code": "CN", "names": ["china"]},
    {"code": "JP", "names": ["japan"]},
    {"code": "CA", "names": ["canada"]},
    {"code": "AU", "names": ["australia"]},
]

# Transaction classification codes for kod_transakcji (field 9)
TRANSACTION_CODE_IMPORT_SERVICES_EU = "IU"   # Import usług z UE
TRANSACTION_CODE_IMPORT_SERVICES_NON_EU = "IU"  # Import usług spoza UE (same code in Rewizor)
