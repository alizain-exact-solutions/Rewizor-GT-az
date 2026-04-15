"""
Rewizor GT EDI++ file writer — v1.12 spec.

Generates a complete ``.epp`` file content from EPP Pydantic models.

Output rules (per InsERT EDI++ 1.12 specification):

  - First section is always ``[INFO]`` (24 fields, one per file).
  - Business documents follow: ``[NAGLOWEK]`` (62 fields) + ``[ZAWARTOSC]``
    (one row of 18 VAT fields per rate).
  - After all business documents, 19 dictionary sections MUST appear in
    order — even when empty — otherwise Rewizor's importer halts.
  - Amounts use 4 decimal places (``200.8500``), dot separator.
  - Dates are ``yyyymmdd000000`` with the time zeroed (except INFO field
    20 which is the real file-generation timestamp).
  - Text fields are wrapped in ``"double quotes"``; optional unfilled text
    fields emit NOTHING between commas (``,,``).
  - Line endings are Windows **CRLF** (``\\r\\n``) — Unix LF causes
    Rewizor to crash.
  - File must end with an extra blank CRLF line after the last
    ``[ZAWARTOSC]``.
  - Encoding: Windows-1250 (``cp1250``). Polish diacritics must not be
    emitted as UTF-8.
"""

import logging
from typing import Dict, Iterable, List, Optional

from src.epp.constants import CONTRACTOR_GROUP_SUPPLIERS
from src.epp.schemas import (
    EPPContractor,
    EPPDocument,
    EPPHeader,
    EPPInfo,
    EPPJpkFlags,
    EPPVatRow,
)
from src.epp.utils import (
    EMPTY,
    build_line,
    encode_win1250,
    format_epp_amount,
    format_epp_date,
    format_epp_datetime,
    format_epp_int,
    join_epp_lines,
    quote_field,
    quote_or_empty,
)

logger = logging.getLogger(__name__)


# ── [INFO] – Table 2, 24 fields ─────────────────────────────────────────────

def _build_info_line(info: EPPInfo, documents: List[EPPDocument]) -> str:
    # Auto-fill period start/end from the set of documents so Rewizor's
    # date-range filter (field 16=1) has a valid window.
    period_start = info.period_start
    period_end = info.period_end
    if documents and (not period_start or not period_end):
        issued = [d.header.issue_date for d in documents if d.header.issue_date]
        if issued:
            period_start = period_start or min(issued)
            period_end = period_end or max(issued)

    fields = [
        quote_field(info.version),                      # 1  Format version "1.12"
        format_epp_int(info.purpose),                   # 2  Communication purpose
        info.codepage,                                  # 3  Codepage (bare "1250")
        quote_field(info.producing_program),            # 4  Producing program
        quote_field(info.sender_id_code),               # 5  Sender ID code
        quote_field(info.sender_short_name),            # 6  Sender short name
        quote_field(info.sender_long_name),             # 7  Sender long name
        quote_field(info.sender_city),                  # 8  Sender city
        quote_field(info.sender_postal_code),           # 9  Sender postal code
        quote_field(info.sender_street),                # 10 Sender street
        quote_field(info.sender_nip),                   # 11 Sender NIP (10 digits)
        quote_field(info.warehouse_code),               # 12 Warehouse code
        quote_field(info.warehouse_name),               # 13 Warehouse name
        quote_field(info.warehouse_description),        # 14 Warehouse description
        quote_or_empty(info.warehouse_analytics),       # 15 Warehouse analytics (usually empty)
        format_epp_int(info.date_range_flag),           # 16 Date range flag
        format_epp_date(period_start),                  # 17 Period start date
        format_epp_date(period_end),                    # 18 Period end date
        quote_field(info.operator_name),                # 19 Operator name
        format_epp_datetime(info.file_generation_timestamp),  # 20 File generation timestamp (real time)
        quote_field(info.country_name),                 # 21 Country name
        quote_field(info.country_prefix),               # 22 EU country prefix
        quote_field(info.eu_vat_number or info.sender_nip),   # 23 EU VAT number
        format_epp_int(info.is_sender_eu),              # 24 Is sender EU
    ]
    return build_line(fields)


# ── [NAGLOWEK] – Table 3, 62 fields ─────────────────────────────────────────

def _build_header_line(h: EPPHeader, info: EPPInfo) -> str:
    """Render the 62-field NAGLOWEK record for one business document."""
    # Field 4 is Rewizor's sequential long-integer counter within the
    # document type; Rewizor reassigns it on import, so a per-document "1"
    # is safe. Field 5 is the number printed on the vendor's paper invoice
    # (e.g. "SHARK 125738"). Field 7 is the KEY used by every auxiliary
    # section — Rewizor auto-prefixes the doc_type ("FZ ") so field 7 stores
    # just the user portion.
    invoice_number = h.supplier_invoice_number or h.full_document_number
    full = h.full_document_number or h.supplier_invoice_number
    sale = h.sale_date or h.issue_date
    receipt = h.receipt_date or h.issue_date
    # Place of issue (field 21) defaults to the sender company's city when
    # the invoice itself doesn't carry one — that's the accountant's own
    # location, which is what Rewizor expects.
    place_of_issue = h.place_of_issue or info.sender_city

    fields = [
        quote_field(h.doc_type),                        # 1  Type
        format_epp_int(h.status),                       # 2  Status
        format_epp_int(h.fiscal_flag),                  # 3  Fiscal flag
        h.numeric_doc_number or "1",                    # 4  Numeric doc# (bare long integer)
        quote_field(invoice_number),                    # 5  Supplier's invoice number (vendor's paper)
        quote_or_empty(h.user_number_suffix),           # 6  User number suffix (optional)
        quote_field(full),                              # 7  Full document number (KEY)
        quote_or_empty(h.corrected_doc_number),         # 8  Corrected document number
        format_epp_date(h.corrected_doc_date) if h.corrected_doc_date else EMPTY,  # 9
        quote_or_empty(h.order_number),                 # 10 Order number
        quote_or_empty(h.target_warehouse),             # 11 Target warehouse
        quote_field(h.contractor_code),                 # 12 Contractor code
        quote_field(h.contractor_short_name),           # 13 Contractor short name
        quote_field(h.contractor_full_name),            # 14 Contractor full name
        quote_field(h.contractor_city),                 # 15 City
        quote_field(h.contractor_postal_code),          # 16 Postal code
        quote_field(h.contractor_street),               # 17 Street
        quote_field(h.contractor_nip),                  # 18 NIP (EU or domestic)
        quote_field(h.category_name),                   # 19 Category ("Zakup"/"Koszty"/"Sprzedaż")
        quote_field(h.category_subtitle),               # 20 Category subtitle
        quote_field(place_of_issue),                    # 21 Place of issue
        format_epp_date(h.issue_date),                  # 22 Issue date
        format_epp_date(sale),                          # 23 Sale date
        format_epp_date(receipt),                       # 24 Receipt date
        format_epp_int(h.vat_lines_count),              # 25 VAT rate line count
        format_epp_int(h.priced_by_net),                # 26 1=net, 0=gross
        quote_field(h.active_price_list),               # 27 Active price list
        format_epp_amount(h.net_value),                 # 28 Net value
        format_epp_amount(h.vat_value),                 # 29 VAT value
        format_epp_amount(h.gross_value),               # 30 Gross value
        format_epp_amount(h.cost),                      # 31 Cost
        quote_or_empty(h.discount_name),                # 32 Discount name
        format_epp_amount(h.discount_percent),          # 33 Discount percent
        quote_field(h.payment_method),                  # 34 Payment method
        format_epp_date(h.payment_due_date) if h.payment_due_date else EMPTY,  # 35
        format_epp_amount(h.paid_at_receipt),           # 36 Paid at receipt
        format_epp_amount(h.amount_due),                # 37 Amount due
        format_epp_int(h.total_rounding),               # 38 Total rounding
        format_epp_int(h.vat_rounding),                 # 39 VAT rounding
        format_epp_int(h.auto_recalculate),             # 40 Auto recalculate
        format_epp_int(h.extended_status),              # 41 Extended status
        quote_field(h.person_issued),                   # 42 Person who issued (quoted empty is OK)
        quote_field(h.person_received),                 # 43 Person who received
        quote_or_empty(h.basis_for_issue),              # 44 Basis for issue
        format_epp_amount(h.packaging_issued),          # 45 Packaging issued
        format_epp_amount(h.packaging_returned),        # 46 Packaging returned
        quote_field(h.currency),                        # 47 Currency
        format_epp_amount(h.fx_rate),                   # 48 FX rate
        quote_field(h.notes),                           # 49 Notes (quoted even when empty — Rewizor expects a text token here)
        quote_or_empty(h.comment),                      # 50 Comment
        quote_or_empty(h.document_subtitle),            # 51 Document subtitle
        quote_or_empty(h.reserved_52),                  # 52 Reserved
        format_epp_int(h.import_already_performed),     # 53 Import already performed
        format_epp_int(h.export_document),              # 54 Export flag
        format_epp_int(h.transaction_type),             # 55 Transaction type
        quote_or_empty(h.card_payment_name),            # 56 Card payment name
        format_epp_amount(h.card_payment_amount),       # 57 Card payment amount
        quote_or_empty(h.credit_payment_name),          # 58 Credit payment name
        format_epp_amount(h.credit_payment_amount),     # 59 Credit payment amount
        quote_field(h.contractor_country_name),         # 60 Country name
        quote_field(h.contractor_country_prefix),       # 61 EU prefix
        format_epp_int(h.contractor_is_eu),             # 62 Is EU
    ]
    return build_line(fields)


# ── [ZAWARTOSC] VAT row – Table 4, 18 fields ───────────────────────────────

def _build_vat_line(row: EPPVatRow) -> str:
    fields = [
        quote_field(row.vat_symbol),                    # 1  Symbol
        format_epp_amount(row.vat_rate),                # 2  Rate (signed; -5 for "oo")
        format_epp_amount(row.net_at_rate),             # 3
        format_epp_amount(row.vat_at_rate),             # 4
        format_epp_amount(row.gross_at_rate),           # 5
        format_epp_amount(row.final_general_net),       # 6
        format_epp_amount(row.final_general_vat),       # 7
        format_epp_amount(row.final_general_gross),     # 8
        format_epp_amount(row.prior_advance_net),       # 9
        format_epp_amount(row.prior_advance_vat),       # 10
        format_epp_amount(row.prior_advance_gross),     # 11
        format_epp_amount(row.prior_advance_net_pln),   # 12
        format_epp_amount(row.prior_advance_vat_pln),   # 13
        format_epp_amount(row.prior_advance_gross_pln), # 14
        format_epp_amount(row.margin_net),              # 15
        format_epp_amount(row.margin_vat),              # 16
        format_epp_amount(row.margin_gross),            # 17
        format_epp_amount(row.purchase_value),          # 18
    ]
    return build_line(fields)


# ── KONTRAHENCI – Table 6.1, 31 fields ──────────────────────────────────────

def _build_contractor_line(c: EPPContractor) -> str:
    # Fields 9–17 (REGON, phone, fax, telex, email, website, contact,
    # supplier analytics, buyer analytics) → 9 empty slots.
    # Fields 18–25 (user fields 1–8) → 8 empty slots.
    # Fields 26–27 (bank name, bank account) → 2 empty slots.
    # NOTE: the v1.12 spec lists 31 fields but the SHARK reference sample
    # (which imports successfully into Rewizor GT) emits only 30 — the ISO
    # country code (field 31) is omitted. We match the working sample.
    empties_9_17 = [EMPTY] * 9
    empties_18_25 = [EMPTY] * 8
    empties_26_27 = [EMPTY] * 2

    fields = [
        format_epp_int(c.contractor_type),              # 1  Contractor type
        quote_field(c.code),                            # 2  Code
        quote_field(c.short_name or c.code),            # 3  Short name
        quote_field(c.full_name or c.short_name or c.code),  # 4  Full name
        quote_field(c.city),                            # 5  City
        quote_field(c.postal_code),                     # 6  Postal code
        quote_field(c.street),                          # 7  Street
        quote_field(c.nip),                             # 8  NIP (EU prefix if foreign)
        *empties_9_17,                                  # 9-17
        *empties_18_25,                                 # 18-25
        *empties_26_27,                                 # 26-27
        quote_field(c.country_name),                    # 28 Country name
        quote_field(c.country_prefix),                  # 29 EU prefix
        format_epp_int(c.is_eu),                        # 30 Is EU
    ]
    return build_line(fields)


# ── DODATKOWEKONTRAHENTOW – Table 6.4, 7 fields ────────────────────────────

def _build_extra_contractor_line(c: EPPContractor) -> str:
    # Defaults mirror the SHARK working example:
    #   code, excise_status=0, excise_treatment=1, cash_method=0,
    #   active_vat_payer=0, create_assignment=0, no_mpp=0
    return build_line([
        quote_field(c.code),                            # 1  Code
        "0",                                            # 2  Excise duty status (undetermined)
        "1",                                            # 3  Excise duty treatment (per product)
        "0",                                            # 4  Cash method flag
        "0",                                            # 5  Active VAT payer
        "0",                                            # 6  Create assignment
        "0",                                            # 7  No split payment for auto
    ])


# ── GRUPYKONTRAHENTOW – Table 6.2, 2 fields ────────────────────────────────

def _build_group_line(code: str, group: str) -> str:
    return build_line([quote_field(code), quote_field(group)])


# ── WYMAGALNOSCMPP – Table 6.6, 2 fields ───────────────────────────────────

def _build_mpp_line(full_doc_number: str, required: int) -> str:
    return build_line([quote_field(full_doc_number), format_epp_int(required)])


# ── DATYZAKONCZENIA – Table 6.5, 2 fields ──────────────────────────────────

def _build_completion_date_line(full_doc_number: str, completion_date: str) -> str:
    return build_line([quote_field(full_doc_number), format_epp_date(completion_date)])


# ── DOKUMENTYZNACZNIKIJPKVAT – Table 6.7, 31 fields ────────────────────────

def _build_jpk_flags_line(f: EPPJpkFlags) -> str:
    fields = [
        quote_field(f.full_document_number),            # 1
        format_epp_int(f.sw),                           # 2
        format_epp_int(f.ee),                           # 3
        format_epp_int(f.tp),                           # 4
        format_epp_int(f.tt_wnt),                       # 5
        format_epp_int(f.tt_d),                         # 6
        format_epp_int(f.mr_t),                         # 7
        format_epp_int(f.mr_uz),                        # 8
        format_epp_int(f.i_42),                         # 9
        format_epp_int(f.i_63),                         # 10
        format_epp_int(f.b_spv),                        # 11
        format_epp_int(f.b_spv_dostawa),                # 12
        format_epp_int(f.b_spv_prowizja),               # 13
        format_epp_int(f.mpp),                          # 14
        format_epp_int(f.imp),                          # 15
        format_epp_int(f.gtu_01),                       # 16
        format_epp_int(f.gtu_02),                       # 17
        format_epp_int(f.gtu_03),                       # 18
        format_epp_int(f.gtu_04),                       # 19
        format_epp_int(f.gtu_05),                       # 20
        format_epp_int(f.gtu_06),                       # 21
        format_epp_int(f.gtu_07),                       # 22
        format_epp_int(f.gtu_08),                       # 23
        format_epp_int(f.gtu_09),                       # 24
        format_epp_int(f.gtu_10),                       # 25
        format_epp_int(f.gtu_11),                       # 26
        format_epp_int(f.gtu_12),                       # 27
        format_epp_int(f.gtu_13),                       # 28
        format_epp_int(f.document_type),                # 29
        format_epp_int(f.wsto_ee),                      # 30
        format_epp_int(f.ied),                          # 31
    ]
    return build_line(fields)


# ── Section assembly helpers ───────────────────────────────────────────────

def _section(keyword: Optional[str], rows: Iterable[str]) -> List[str]:
    """Emit a labelled dictionary section.

    When *keyword* is None the caller is responsible for the section label
    (business documents use [NAGLOWEK] with the full 62-field record, not
    a keyword). For dictionary sections [NAGLOWEK] is followed by the
    keyword string, then [ZAWARTOSC] with zero-or-more rows.
    """
    out: List[str] = ["[NAGLOWEK]"]
    if keyword is not None:
        out.append(quote_field(keyword))
    out.append("[ZAWARTOSC]")
    out.extend(rows)
    # Trailing blank line between sections — matches the SHARK working sample
    # and keeps Rewizor's label-by-label parser happy.
    out.append("")
    return out


# ── Public API ─────────────────────────────────────────────────────────────

def generate_epp(info: EPPInfo, documents: List[EPPDocument]) -> str:
    """Build the full EPP file content as a Unicode string.

    Use :func:`generate_epp_bytes` to get Windows-1250 bytes ready for
    file output.
    """
    lines: List[str] = []

    # ── [INFO] ──
    lines.append("[INFO]")
    lines.append(_build_info_line(info, documents))
    lines.append("")

    # ── Business documents: one NAGLOWEK + ZAWARTOSC pair each ──
    for doc in documents:
        lines.append("[NAGLOWEK]")
        lines.append(_build_header_line(doc.header, info))
        lines.append("[ZAWARTOSC]")
        for vat_row in doc.vat_rows:
            lines.append(_build_vat_line(vat_row))
        lines.append("")

    # ── Aggregate dictionary data across all documents ──
    # Deduplicate contractors by unique code; first occurrence wins.
    contractors: Dict[str, EPPContractor] = {}
    groups: Dict[str, str] = {}  # code → group name
    for doc in documents:
        code = doc.contractor.code
        if code and code not in contractors:
            contractors[code] = doc.contractor
            groups[code] = doc.contractor_group or CONTRACTOR_GROUP_SUPPLIERS

    # ── KONTRAHENCI ──
    lines.extend(_section("KONTRAHENCI", [
        _build_contractor_line(c) for c in contractors.values()
    ]))

    # ── GRUPYKONTRAHENTOW ──
    lines.extend(_section("GRUPYKONTRAHENTOW", [
        _build_group_line(code, group) for code, group in groups.items()
    ]))

    # ── CECHYKONTRAHENTOW (empty — we don't tag contractors) ──
    lines.extend(_section("CECHYKONTRAHENTOW", []))

    # ── DODATKOWEKONTRAHENTOW ──
    lines.extend(_section("DODATKOWEKONTRAHENTOW", [
        _build_extra_contractor_line(c) for c in contractors.values()
    ]))

    # ── IDENTYFIKATORYPLATNOSCI (Navireo only; always empty on GT) ──
    lines.extend(_section("IDENTYFIKATORYPLATNOSCI", []))

    # ── DATYZAKONCZENIA (one row per document that has a completion date) ──
    completion_rows: List[str] = []
    for doc in documents:
        full = _full_key(doc.header)
        completion = doc.completion_date or doc.header.sale_date or doc.header.issue_date
        if full and completion:
            completion_rows.append(_build_completion_date_line(full, completion))
    lines.extend(_section("DATYZAKONCZENIA", completion_rows))

    # ── NUMERYIDENTYFIKACYJNENABYWCOW (empty; we don't track buyer IDs) ──
    lines.extend(_section("NUMERYIDENTYFIKACYJNENABYWCOW", []))

    # ── DOKUMENTYFISKALNEVAT (empty; we don't emit fiscal reports) ──
    lines.extend(_section("DOKUMENTYFISKALNEVAT", []))

    # ── OPLATYDODATKOWE / OPLATYSPECJALNE (empty) ──
    lines.extend(_section("OPLATYDODATKOWE", []))
    lines.extend(_section("OPLATYSPECJALNE", []))

    # ── WYMAGALNOSCMPP (one row per document) ──
    mpp_rows: List[str] = []
    for doc in documents:
        full = _full_key(doc.header)
        if full:
            mpp_rows.append(_build_mpp_line(full, doc.mpp_required))
    lines.extend(_section("WYMAGALNOSCMPP", mpp_rows))

    # ── DOKUMENTYZNACZNIKIJPKVAT (one row per document) ──
    jpk_rows: List[str] = []
    for doc in documents:
        full = _full_key(doc.header)
        if not full:
            continue
        flags = doc.jpk_flags or EPPJpkFlags(full_document_number=full)
        # Ensure the key matches the header (defensive; mapper sets this).
        if flags.full_document_number != full:
            flags = flags.model_copy(update={"full_document_number": full})
        jpk_rows.append(_build_jpk_flags_line(flags))
    lines.extend(_section("DOKUMENTYZNACZNIKIJPKVAT", jpk_rows))

    # ── Remaining v1.12 sections (all empty for our export profile) ──
    for keyword in (
        "OPLATACUKROWA",
        "SPECYFIKACJATOWAROWAWSTO",
        "PLATNOSCI",
        "INFORMACJEWSTO",
        "STAWKIVATZAGRANICZNE",
        "DATYUJECIAKOREKT",
        "DOKUMENTYKSEF",
    ):
        lines.extend(_section(keyword, []))

    # ``join_epp_lines`` adds CRLF between lines and a trailing blank CRLF.
    return join_epp_lines(lines)


def _full_key(h: EPPHeader) -> str:
    """Build the auxiliary-section key: "<doc_type> <full_document_number>".

    Rewizor matches rows in WYMAGALNOSCMPP, DATYZAKONCZENIA,
    DOKUMENTYZNACZNIKIJPKVAT etc. using this concatenation — the header
    stores only the user portion in field 7 (e.g. "SHARK 125738"), and
    the importer prefixes the document type when linking auxiliary rows.
    """
    number = h.full_document_number or h.numeric_doc_number
    if not number:
        return ""
    return f"{h.doc_type} {number}"


def generate_epp_bytes(info: EPPInfo, documents: List[EPPDocument]) -> bytes:
    """Build the EPP file and encode it to Windows-1250 bytes."""
    text = generate_epp(info, documents)
    logger.info(
        "Generated EPP file: %d document(s), %d chars, %d bytes (cp1250)",
        len(documents),
        len(text),
        len(text.encode("cp1250", errors="replace")),
    )
    return encode_win1250(text)
