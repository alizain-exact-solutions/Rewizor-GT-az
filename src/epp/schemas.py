"""
Pydantic models for Rewizor GT EDI++ (EPP) file sections — v1.12 spec.

Field ordering matches the InsERT EDI++ 1.12 specification tables:

  * :class:`EPPInfo`        – [INFO]               24 fields  (Table 2)
  * :class:`EPPHeader`      – [NAGLOWEK]           62 fields  (Table 3)
  * :class:`EPPVatRow`      – [ZAWARTOSC]          18 fields  (Table 4)
  * :class:`EPPContractor`  – KONTRAHENCI          31 fields  (Table 6.1)
  * :class:`EPPJpkFlags`    – DOKUMENTYZNACZNIKIJPKVAT 31 fields (6.7)

:class:`EPPDocument` bundles the document-specific records (header,
VAT rows, contractor card, MPP flag, completion date, JPK flags) so the
writer can emit one top-level [NAGLOWEK]/[ZAWARTOSC] per document and
later collect the auxiliary rows into their dictionary sections.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.epp.constants import (
    CONTRACTOR_GROUP_SUPPLIERS,
    CONTRACTOR_TYPE_BOTH,
    DOC_TYPE_PURCHASE_INVOICE,
    EPP_ENCODING_WIN1250,
    EPP_PURPOSE_ACCOUNTING_OFFICE,
    EPP_VERSION,
    PAYMENT_TRANSFER,
    TXN_TYPE_DOMESTIC,
    VALID_DOC_TYPES,
    VALID_PAYMENT_METHODS,
    VALID_VAT_SYMBOLS,
)


# ── Table 2: [INFO] – 24 fields ─────────────────────────────────────────────

class EPPInfo(BaseModel):
    """File-level header — appears exactly once at the top of the EPP file.

    All 24 fields of EDI++ Table 2 (v1.12).
    """

    version: str = EPP_VERSION                          # 1  Format version  ("1.12")
    purpose: int = EPP_PURPOSE_ACCOUNTING_OFFICE        # 2  Communication purpose
    codepage: str = EPP_ENCODING_WIN1250                # 3  Codepage ("1250")
    producing_program: str = "Subiekt GT"               # 4  Producing program name
    sender_id_code: str = ""                            # 5  Sender ID code (short)
    sender_short_name: str = ""                         # 6  Sender short name
    sender_long_name: str = ""                          # 7  Sender long name (company)
    sender_city: str = ""                               # 8  Sender city
    sender_postal_code: str = ""                        # 9  Sender postal code
    sender_street: str = ""                             # 10 Sender street + number
    sender_nip: str = ""                                # 11 Sender NIP (10 digits, NO "PL" prefix)
    warehouse_code: str = "MAG"                         # 12 Warehouse code
    warehouse_name: str = "Główny"                      # 13 Warehouse short name
    warehouse_description: str = "Magazyn główny"       # 14 Warehouse description
    warehouse_analytics: str = ""                       # 15 Warehouse analytics (empty)
    date_range_flag: int = 1                            # 16 Date range flag (1=relevant)
    period_start: Optional[str] = None                  # 17 Period start date (yyyymmdd000000)
    period_end: Optional[str] = None                    # 18 Period end date
    operator_name: str = "Szef"                         # 19 Operator name
    file_generation_timestamp: Optional[str] = None     # 20 File generation timestamp (real time)
    country_name: str = "Polska"                        # 21 Country name
    country_prefix: str = "PL"                          # 22 EU country prefix
    eu_vat_number: str = ""                             # 23 EU VAT number (with PL prefix if EU)
    is_sender_eu: int = 0                               # 24 Is sender EU entity (0 or 1)


# ── Table 4: [ZAWARTOSC] (VAT breakdown) – 18 fields ────────────────────────

class EPPVatRow(BaseModel):
    """Single VAT-rate breakdown row. Count must match header field 25."""

    @field_validator("vat_symbol")
    @classmethod
    def validate_vat_symbol(cls, v: str) -> str:
        if v not in VALID_VAT_SYMBOLS:
            raise ValueError(
                f"Invalid vat_symbol '{v}'. Must be one of: {sorted(VALID_VAT_SYMBOLS)}"
            )
        return v

    vat_symbol: str                                     # 1  "23","8","5","0","zw","np","oo","ex","ue","npo"
    vat_rate: float                                     # 2  23.0 or special marker (-1,-2,-3,-4,-5)
    net_at_rate: float = 0.0                            # 3  Net at this rate
    vat_at_rate: float = 0.0                            # 4  VAT at this rate
    gross_at_rate: float = 0.0                          # 5  Gross at this rate
    final_general_net: float = 0.0                      # 6  Final general net (= field 3 for regular)
    final_general_vat: float = 0.0                      # 7  Final general VAT (= field 4)
    final_general_gross: float = 0.0                    # 8  Final general gross (= field 5)
    prior_advance_net: float = 0.0                      # 9  Prior advance net (0 for regular)
    prior_advance_vat: float = 0.0                      # 10 Prior advance VAT
    prior_advance_gross: float = 0.0                    # 11 Prior advance gross
    prior_advance_net_pln: float = 0.0                  # 12 Prior advance net PLN
    prior_advance_vat_pln: float = 0.0                  # 13 Prior advance VAT PLN
    prior_advance_gross_pln: float = 0.0                # 14 Prior advance gross PLN
    margin_net: float = 0.0                             # 15 Margin net (FM only)
    margin_vat: float = 0.0                             # 16 Margin VAT (FM only)
    margin_gross: float = 0.0                           # 17 Margin gross (FM only)
    purchase_value: float = 0.0                         # 18 Purchase value (FM only)


# ── Table 3: [NAGLOWEK] – 62 fields ─────────────────────────────────────────

class EPPHeader(BaseModel):
    """Document header — one per business document (FZ, FS, …).

    Every document type shares the same 62-field layout; field 1 selects
    the type. Defaults reflect a typical FZ (purchase invoice) from a
    Polish supplier paid by bank transfer.
    """

    model_config = ConfigDict(validate_assignment=True)

    @field_validator("doc_type")
    @classmethod
    def _validate_doc_type(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in VALID_DOC_TYPES:
            raise ValueError(
                f"Invalid doc_type '{v}'. Must be one of: {sorted(VALID_DOC_TYPES)}"
            )
        return v

    @field_validator("issue_date")
    @classmethod
    def _validate_issue_date(cls, v: str) -> str:
        if not v:
            raise ValueError("issue_date is required")
        return v

    @field_validator("payment_method")
    @classmethod
    def _validate_payment_method(cls, v: str) -> str:
        # Empty is allowed (used for foreign / unpaid docs).
        if v and v not in VALID_PAYMENT_METHODS:
            raise ValueError(
                f"Invalid payment_method '{v}'. Must be one of: {sorted(VALID_PAYMENT_METHODS)} or empty"
            )
        return v

    # ── 4.1 Basic parameters (1–11) ──
    doc_type: str = DOC_TYPE_PURCHASE_INVOICE           # 1  Document type
    status: int = 1                                     # 2  0=deferred, 1=executed
    fiscal_flag: int = 0                                # 3  Fiscal registration flag
    numeric_doc_number: str = ""                        # 4  Numeric document number (sequential)
    supplier_invoice_number: str = ""                   # 5  Supplier's invoice number (vendor's paper) – optional
    user_number_suffix: str = ""                        # 6  User number suffix – optional
    full_document_number: str = ""                      # 7  KEY: "SHARK 125738" (Rewizor prefixes doc_type)
    corrected_doc_number: str = ""                      # 8  Corrections only
    corrected_doc_date: Optional[str] = None            # 9  Corrections only
    order_number: str = ""                              # 10 Inter-warehouse transfers only
    target_warehouse: str = ""                          # 11 MM only

    # ── 4.2 Contractor (12–18) ──
    contractor_code: str = ""                           # 12 Links to KONTRAHENCI card
    contractor_short_name: str = ""                     # 13 Short name
    contractor_full_name: str = ""                      # 14 Full name
    contractor_city: str = ""                           # 15 City
    contractor_postal_code: str = ""                    # 16 Postal code
    contractor_street: str = ""                         # 17 Street + number
    contractor_nip: str = ""                            # 18 NIP (EU prefix if foreign, e.g. "NL862287339B01")

    # ── 4.3 Category, place and dates (19–24) ──
    category_name: str = "Zakup"                        # 19 "Zakup" → GL 401, "Koszty" → GL 302
    category_subtitle: str = "Zakup towarów lub usług"  # 20 Category subtitle
    place_of_issue: str = ""                            # 21 Place of issue
    issue_date: str = ""                                # 22 Issue date (yyyymmdd000000)
    sale_date: Optional[str] = None                     # 23 Sale / delivery date
    receipt_date: Optional[str] = None                  # 24 Receipt date

    # ── 4.4 Positions, pricing, values (25–31) ──
    vat_lines_count: int = 1                            # 25 Number of VAT rate lines in [ZAWARTOSC]
    priced_by_net: int = 1                              # 26 1=net, 0=gross
    active_price_list: str = "Cena ostatniej dost."     # 27 Active price list name
    net_value: float = 0.0                              # 28 Net value
    vat_value: float = 0.0                              # 29 VAT value
    gross_value: float = 0.0                            # 30 Gross value
    cost: float = 0.0                                   # 31 Cost (typically = net for regular)

    # ── 4.5 Discount and payment (32–37) ──
    discount_name: str = ""                             # 32 Discount name (empty if no discount)
    discount_percent: float = 0.0                       # 33 Discount percent
    payment_method: str = PAYMENT_TRANSFER              # 34 "przelew", "gotówka", "karta", "kompensata", ""
    payment_due_date: Optional[str] = None              # 35 Payment due date
    paid_at_receipt: float = 0.0                        # 36 0 for transfer, gross for cash
    amount_due: float = 0.0                             # 37 Full gross for transfer, 0 for cash

    # ── 4.6 Rounding and auto-recalculate (38–40) ──
    total_rounding: int = 0                             # 38 0=1 grosz, 1=10 groszy, 2=1 zloty
    vat_rounding: int = 0                               # 39 0=1 grosz, 1=10 groszy, 2=1 zloty
    auto_recalculate: int = 1                           # 40 Always 1

    # ── 4.7 Extended status (41) ──
    extended_status: int = 0                            # 41 0=normal

    # ── 4.8 Personnel and packaging (42–46) ──
    person_issued: str = ""                             # 42 Person who issued (may be leading ';' for title)
    person_received: str = "Szef"                       # 43 Person who received
    basis_for_issue: str = ""                           # 44 Basis for issue
    packaging_issued: float = 0.0                       # 45 Packaging issued
    packaging_returned: float = 0.0                     # 46 Packaging returned

    # ── 4.9 Currency (47–48) ──
    currency: str = "PLN"                               # 47 Currency symbol
    fx_rate: float = 1.0                                # 48 FX rate (1.0 for PLN)

    # ── 4.10 Notes and flags (49–54) ──
    notes: str = ""                                     # 49 Notes (transaction IDs, references)
    comment: str = ""                                   # 50 Comment
    document_subtitle: str = ""                         # 51 Document subtitle
    reserved_52: str = ""                               # 52 Reserved – leave empty
    import_already_performed: int = 0                   # 53 0x00/0x01/0x02
    export_document: int = 0                            # 54 Export document flag

    # ── 4.11 Transaction type (55) ──
    transaction_type: int = TXN_TYPE_DOMESTIC           # 55 0=domestic, 11=IMUn, 21=OOu, 22=WSTO, ...

    # ── 4.12 Card payments and contractor country (56–62) ──
    card_payment_name: str = ""                         # 56 Card payment name
    card_payment_amount: float = 0.0                    # 57 Card payment amount
    credit_payment_name: str = ""                       # 58 Credit payment name
    credit_payment_amount: float = 0.0                  # 59 Credit payment amount
    contractor_country_name: str = "Polska"             # 60 "Polska", "Holandia", ...
    contractor_country_prefix: str = "PL"               # 61 "PL", "NL", ...
    contractor_is_eu: int = 0                           # 62 0=domestic, 1=EU


# ── Table 6.1: KONTRAHENCI – 31 fields ─────────────────────────────────────

class EPPContractor(BaseModel):
    """KONTRAHENCI dictionary entry — contractor card (31 fields)."""

    contractor_type: int = CONTRACTOR_TYPE_BOTH         # 1  0=buyer/supplier
    code: str                                           # 2  UNIQUE – referenced in header field 12
    short_name: str = ""                                # 3
    full_name: str = ""                                 # 4
    city: str = ""                                      # 5
    postal_code: str = ""                               # 6
    street: str = ""                                    # 7
    nip: str = ""                                       # 8  NIP incl. EU prefix
    # 9-17 are free-form metadata fields (REGON, phone, fax, telex, email,
    # website, contact, supplier analytics, buyer analytics) – left empty.
    # 18-25 are 8 user free-text fields – left empty.
    # 26-27 are bank name and bank account – left empty.
    country_name: str = "Polska"                        # 28
    country_prefix: str = "PL"                          # 29
    is_eu: int = 0                                      # 30 0=domestic, 1=EU
    iso_country_code: str = ""                          # 31 duplicated alpha-2 code


# ── Table 6.7: DOKUMENTYZNACZNIKIJPKVAT – 31 fields ────────────────────────

class EPPJpkFlags(BaseModel):
    """JPK_V7 flags for one document. All booleans default to 0."""

    full_document_number: str                           # 1  Must match header field 7 verbatim
    # Fields 2-28: boolean JPK_V7 flags
    sw: int = 0                                         # 2  Distance sales
    ee: int = 0                                         # 3  Electronic services (art. 28k)
    tp: int = 0                                         # 4  Related-party transaction
    tt_wnt: int = 0                                     # 5  Triangular intra-EU acquisition
    tt_d: int = 0                                       # 6  Triangular delivery
    mr_t: int = 0                                       # 7  VAT margin tourism
    mr_uz: int = 0                                      # 8  VAT margin used goods
    i_42: int = 0                                       # 9  Customs procedure 42
    i_63: int = 0                                       # 10 Customs procedure 63
    b_spv: int = 0                                      # 11 Single-purpose voucher transfer
    b_spv_dostawa: int = 0                              # 12 Goods/services for SPV
    b_spv_prowizja: int = 0                             # 13 SPV commission
    mpp: int = 0                                        # 14 Split payment
    imp: int = 0                                        # 15 Import
    gtu_01: int = 0                                     # 16
    gtu_02: int = 0                                     # 17
    gtu_03: int = 0                                     # 18
    gtu_04: int = 0                                     # 19
    gtu_05: int = 0                                     # 20
    gtu_06: int = 0                                     # 21
    gtu_07: int = 0                                     # 22
    gtu_08: int = 0                                     # 23
    gtu_09: int = 0                                     # 24
    gtu_10: int = 0                                     # 25
    gtu_11: int = 0                                     # 26
    gtu_12: int = 0                                     # 27
    gtu_13: int = 0                                     # 28
    # Field 29 is NOT boolean — it's a byte enum.
    document_type: int = 0                              # 29 0=none, 1=RO, 2=WEW, 3=FP, 4=MK, 5=VAT_RR
    wsto_ee: int = 0                                    # 30 WSTO electronic services
    ied: int = 0                                        # 31 Import of electronic devices


# ── Composite ────────────────────────────────────────────────────────────────

class EPPDocument(BaseModel):
    """One invoice with its VAT breakdown plus auxiliary dictionary data.

    Rewizor GT requires auxiliary rows (KONTRAHENCI, WYMAGALNOSCMPP,
    DOKUMENTYZNACZNIKIJPKVAT, DATYZAKONCZENIA) per document; the writer
    deduplicates contractors across documents when rendering.
    """

    header: EPPHeader
    vat_rows: List[EPPVatRow] = Field(default_factory=list)
    contractor: EPPContractor                           # Emitted into KONTRAHENCI
    contractor_group: str = CONTRACTOR_GROUP_SUPPLIERS  # GRUPYKONTRAHENTOW ("Dostawcy"/"Odbiorcy")
    mpp_required: int = 0                               # WYMAGALNOSCMPP (0=no)
    completion_date: Optional[str] = None               # DATYZAKONCZENIA
    jpk_flags: Optional[EPPJpkFlags] = None             # DOKUMENTYZNACZNIKIJPKVAT (built from full_document_number)
