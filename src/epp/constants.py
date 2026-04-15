"""
Rewizor GT EDI++ constants (v1.12 spec).

VAT symbols, document types, payment methods, country name mappings,
transaction type codes, and JPK_V7 flag structure used throughout
the EPP export pipeline.
"""

from typing import Any

# ---------------------------------------------------------------------------
# EDI++ file metadata
# ---------------------------------------------------------------------------
EPP_VERSION = "1.12"
EPP_PURPOSE_ACCOUNTING_OFFICE = 0   # 0=accounting office, 1=sales rep, 2=head office, 3=other
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

# Purchase-side documents (Dostawcy group, purchase register)
PURCHASE_DOC_TYPES = {
    DOC_TYPE_PURCHASE_INVOICE,
    DOC_TYPE_PURCHASE_COSTS,
    DOC_TYPE_PURCHASE_INVOICE_CORRECTION,
    DOC_TYPE_PURCHASE_COSTS_CORRECTION,
}

# Sales-side documents (Odbiorcy group, sales register)
SALES_DOC_TYPES = {
    DOC_TYPE_SALES_INVOICE,
    DOC_TYPE_SALES_COSTS,
    DOC_TYPE_SALES_INVOICE_CORRECTION,
    DOC_TYPE_SALES_COSTS_CORRECTION,
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

# Contractor group names in Rewizor (KONTRAHENCI → GRUPYKONTRAHENTOW)
CONTRACTOR_GROUP_SUPPLIERS = "Dostawcy"
CONTRACTOR_GROUP_BUYERS = "Odbiorcy"

# Contractor type byte (KONTRAHENCI field 1)
CONTRACTOR_TYPE_BOTH = 0        # buyer/supplier
CONTRACTOR_TYPE_SUPPLIER = 1    # supplier only
CONTRACTOR_TYPE_BUYER = 2       # buyer only

# ---------------------------------------------------------------------------
# VAT symbols  (Table 4 – pole "Symbol stawki")
# ---------------------------------------------------------------------------
VAT_SYMBOL_23 = "23"
VAT_SYMBOL_8 = "8"
VAT_SYMBOL_5 = "5"
VAT_SYMBOL_0 = "0"
VAT_SYMBOL_EXEMPT = "zw"                # Zwolniony (-1.00)
VAT_SYMBOL_EXPORT = "ex"                # Eksportowy (-2.00)
VAT_SYMBOL_EU_SUPPLY = "ue"             # Unijny (-3.00)
VAT_SYMBOL_NOT_DEDUCTIBLE = "npo"       # Nie podlegający odliczeniu (-4.00)
VAT_SYMBOL_REVERSE_CHARGE = "oo"        # Odwrotne obciążenie (-5.00) - letter 'o', not zero
VAT_SYMBOL_NOT_APPLICABLE = "np"        # Nie podlega (alias kept for OCR compatibility)

VALID_VAT_SYMBOLS = {
    VAT_SYMBOL_23,
    VAT_SYMBOL_8,
    VAT_SYMBOL_5,
    VAT_SYMBOL_0,
    VAT_SYMBOL_EXEMPT,
    VAT_SYMBOL_EXPORT,
    VAT_SYMBOL_EU_SUPPLY,
    VAT_SYMBOL_NOT_DEDUCTIBLE,
    VAT_SYMBOL_REVERSE_CHARGE,
    VAT_SYMBOL_NOT_APPLICABLE,
}

# Map numeric VAT rates to their canonical symbol string
RATE_TO_SYMBOL: dict[float, str] = {
    23.0: VAT_SYMBOL_23,
    8.0: VAT_SYMBOL_8,
    5.0: VAT_SYMBOL_5,
    0.0: VAT_SYMBOL_0,
}

# Special rate markers (EDI++ Table 4 field 2)
VAT_RATE_EXEMPT = -1.0              # "zw"
VAT_RATE_EXPORT = -2.0              # "ex"
VAT_RATE_EU_SUPPLY = -3.0           # "ue"
VAT_RATE_NOT_DEDUCTIBLE = -4.0      # "npo"
VAT_RATE_REVERSE_CHARGE = -5.0      # "oo"
# "np" is typically treated as -1.0 (Rewizor accepts zw/np interchangeably for
# transactions not subject to Polish VAT).
VAT_RATE_NOT_APPLICABLE = -1.0

# ---------------------------------------------------------------------------
# Payment methods  (Table 3 field 34 – pole "Forma płatności")
#
# Values must match the Rewizor GT configuration table. Use descriptive
# Polish names — single-letter codes are NOT accepted by v1.12 import.
# ---------------------------------------------------------------------------
PAYMENT_TRANSFER = "przelew"
PAYMENT_CASH = "gotówka"
PAYMENT_CARD = "karta"
PAYMENT_COMPENSATION = "kompensata"

VALID_PAYMENT_METHODS = {
    PAYMENT_TRANSFER,
    PAYMENT_CASH,
    PAYMENT_CARD,
    PAYMENT_COMPENSATION,
}

# Maps input variants (old single-letter codes, English, accent-less Polish)
# to the canonical Rewizor method name.
PAYMENT_METHOD_ALIASES: dict[str, str] = {
    # canonical
    "przelew": PAYMENT_TRANSFER,
    "gotówka": PAYMENT_CASH,
    "karta": PAYMENT_CARD,
    "kompensata": PAYMENT_COMPENSATION,
    # accent-less Polish (OCR output)
    "gotowka": PAYMENT_CASH,
    # legacy single-letter codes (v1.10 era)
    "p": PAYMENT_TRANSFER,
    "g": PAYMENT_CASH,
    "k": PAYMENT_CARD,
    "o": PAYMENT_COMPENSATION,
    # English aliases
    "transfer": PAYMENT_TRANSFER,
    "bank transfer": PAYMENT_TRANSFER,
    "wire transfer": PAYMENT_TRANSFER,
    "cash": PAYMENT_CASH,
    "card": PAYMENT_CARD,
    "credit card": PAYMENT_CARD,
    "compensation": PAYMENT_COMPENSATION,
}

# ---------------------------------------------------------------------------
# Transaction types (Table 3 field 55 – "Rodzaj transakcji VAT")
# ---------------------------------------------------------------------------
TXN_TYPE_DOMESTIC = 0              # S/Z – vendor charges Polish VAT (incl. OSS)
TXN_TYPE_IMPORT_EXPORT = 1         # EX / IM
TXN_TYPE_INTRA_EU = 2              # WDT / WNT
TXN_TYPE_TRIANGULAR = 3            # WTTD / WTTN
TXN_TYPE_IMPORT_EXPORT_SERVICES = 4  # EXU / IMU (old code)
TXN_TYPE_REVERSE_CHARGE = 6        # OOs / OOz
TXN_TYPE_INTRA_EU_WNTN = 10        # WNTn
TXN_TYPE_IMPORT_SERVICES = 11      # IMUn – modern JPK_V7M code for import of services
TXN_TYPE_SUPPLY_OUTSIDE_PL = 12    # SPTK
TXN_TYPE_REVERSE_CHARGE_SERVICES = 21  # OOu – domestic reverse charge on services
TXN_TYPE_WSTO_INTRA_EU = 22        # WSTO intra-EU distance sales

# ---------------------------------------------------------------------------
# Country classification — EU vs NON-EU
#
# Each entry maps an ISO 3166-1 alpha-2 code to lowercase name aliases
# that may appear in messy OCR / invoice text, plus the Polish country
# name used by Rewizor.
# ---------------------------------------------------------------------------

EU_COUNTRIES: list[dict[str, Any]] = [
    {"code": "AT", "names": ["austria"], "pl": "Austria"},
    {"code": "BE", "names": ["belgium"], "pl": "Belgia"},
    {"code": "BG", "names": ["bulgaria"], "pl": "Bułgaria"},
    {"code": "HR", "names": ["croatia"], "pl": "Chorwacja"},
    {"code": "CY", "names": ["cyprus"], "pl": "Cypr"},
    {"code": "CZ", "names": ["czech republic", "czechia"], "pl": "Czechy"},
    {"code": "DK", "names": ["denmark"], "pl": "Dania"},
    {"code": "EE", "names": ["estonia"], "pl": "Estonia"},
    {"code": "FI", "names": ["finland"], "pl": "Finlandia"},
    {"code": "FR", "names": ["france"], "pl": "Francja"},
    {"code": "DE", "names": ["germany"], "pl": "Niemcy"},
    {"code": "GR", "names": ["greece"], "pl": "Grecja"},
    {"code": "HU", "names": ["hungary"], "pl": "Węgry"},
    {"code": "IE", "names": ["ireland"], "pl": "Irlandia"},
    {"code": "IT", "names": ["italy"], "pl": "Włochy"},
    {"code": "LV", "names": ["latvia"], "pl": "Łotwa"},
    {"code": "LT", "names": ["lithuania"], "pl": "Litwa"},
    {"code": "LU", "names": ["luxembourg"], "pl": "Luksemburg"},
    {"code": "MT", "names": ["malta"], "pl": "Malta"},
    {"code": "NL", "names": ["netherlands", "holland"], "pl": "Holandia"},
    {"code": "PL", "names": ["poland", "polska"], "pl": "Polska"},
    {"code": "PT", "names": ["portugal"], "pl": "Portugalia"},
    {"code": "RO", "names": ["romania"], "pl": "Rumunia"},
    {"code": "SK", "names": ["slovakia"], "pl": "Słowacja"},
    {"code": "SI", "names": ["slovenia"], "pl": "Słowenia"},
    {"code": "ES", "names": ["spain"], "pl": "Hiszpania"},
    {"code": "SE", "names": ["sweden"], "pl": "Szwecja"},
]

# Derived set for fast ISO-code lookups
EU_MEMBER_STATES: set[str] = {c["code"] for c in EU_COUNTRIES}

NON_EU_COUNTRIES: list[dict[str, Any]] = [
    {"code": "US", "names": ["united states", "usa"], "pl": "Stany Zjednoczone"},
    {"code": "GB", "names": ["united kingdom", "uk", "great britain"], "pl": "Wielka Brytania"},
    {"code": "SG", "names": ["singapore"], "pl": "Singapur"},
    {"code": "CH", "names": ["switzerland"], "pl": "Szwajcaria"},
    {"code": "NO", "names": ["norway"], "pl": "Norwegia"},
    {"code": "AE", "names": ["uae", "united arab emirates"], "pl": "Zjednoczone Emiraty Arabskie"},
    {"code": "IN", "names": ["india"], "pl": "Indie"},
    {"code": "CN", "names": ["china"], "pl": "Chiny"},
    {"code": "JP", "names": ["japan"], "pl": "Japonia"},
    {"code": "CA", "names": ["canada"], "pl": "Kanada"},
    {"code": "AU", "names": ["australia"], "pl": "Australia"},
]

# ISO code → Polish country name (used for NAGLOWEK field 60 and KONTRAHENCI field 28)
COUNTRY_PL_NAMES: dict[str, str] = {}
for _entry in (*EU_COUNTRIES, *NON_EU_COUNTRIES):
    COUNTRY_PL_NAMES[_entry["code"]] = _entry["pl"]


def polish_country_name(iso_code: str, default: str = "") -> str:
    """Return the Polish country name for an ISO alpha-2 code.

    Empty code or unknown code → *default*.
    """
    if not iso_code:
        return default
    return COUNTRY_PL_NAMES.get(iso_code.strip().upper(), default or iso_code)


# Transaction classification codes for kod_transakcji (Table 3 field 9)
# Empty by default; only set for cross-border scenarios so Rewizor's posting
# scheme picks the correct GL account.
TRANSACTION_CODE_IMPORT_SERVICES = "IU"      # Import usług (EU & NON-EU)
TRANSACTION_CODE_INTRA_EU = "WNT"            # Wewnątrzwspólnotowe nabycie towarów
TRANSACTION_CODE_EXPORT_SERVICES = "EU"      # Export usług
