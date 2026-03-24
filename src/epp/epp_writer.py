"""
Rewizor GT EDI++ file writer.

Generates the complete ``.epp`` file content from EPP Pydantic models.

Output rules (per InsERT EDI++ 1.12 specification):
  - Sections start with a tag on its own line: ``[INFO]``, ``[NAGLOWEK]``, ``[ZAWARTOSC]``
  - Fields within a record are comma-separated on one line
  - Dates: ``yyyymmdd000000`` (time portion zeroed)
  - Numbers: dot decimal, no thousands separator
  - Strings: double-quoted when they may contain commas
  - File **must** end with a blank line
  - Encoding: Windows-1250
"""

import logging
from typing import List

from src.epp.schemas import EPPDocument, EPPInfo
from src.epp.utils import (
    encode_win1250,
    format_epp_amount,
    format_epp_date,
    quote_field,
)

logger = logging.getLogger(__name__)


def _build_info_line(info: EPPInfo) -> str:
    """Render the [INFO] section – Table 2, fields 1-19."""
    fields = [
        info.version,                           # 1  Wersja
        str(info.purpose),                      # 2  Cel
        info.encoding,                          # 3  Kodowanie
        quote_field(info.generator_name),       # 4  Nazwa programu
        quote_field(info.generator_nip),        # 5  NIP programu
        quote_field(info.generator_city),       # 6  Miejscowość programu
        quote_field(info.company_name),         # 7  Nazwa firmy
        "",                                     # 8  Ulica firmy
        "",                                     # 9  Miasto firmy
        "",                                     # 10 Kod pocztowy firmy
        quote_field(info.company_nip),          # 11 NIP firmy (with prefix)
        "",                                     # 12
        "",                                     # 13
        "",                                     # 14
        "",                                     # 15
        "",                                     # 16
        "",                                     # 17
        "",                                     # 18
        "",                                     # 19
    ]
    return ",".join(fields)


def _build_header_line(doc: EPPDocument) -> str:
    """Render one [NAGLOWEK] record – Table 3, all 51 fields."""
    h = doc.header
    sale = h.sale_date or h.issue_date
    receipt = h.receipt_date or h.issue_date
    due = h.payment_due_date or ""

    fields = [
        quote_field(h.doc_type),                # 1  Typ
        str(h.lp_dekretacji),                   # 2  Lp dekretacji
        str(h.rodzaj_dokumentu),                # 3  Rodzaj dokumentu
        str(h.rodzaj_rejestru),                 # 4  Rodzaj rejestru
        h.numer_rejestru,                       # 5  Numer rejestru
        quote_field(h.doc_number),              # 6  Numer dokumentu
        h.numer_ewidencyjny,                    # 7  Numer ewidencyjny
        quote_field(h.numer_oryginalny or h.doc_number),  # 8  Numer oryginalny
        h.kod_transakcji,                       # 9  Kod transakcji
        h.field_10,                             # 10 (reserved)
        quote_field(h.contractor_symbol),       # 11 Symbol kontrahenta
        quote_field(h.contractor_code or h.contractor_symbol),  # 12 Kod kontrahenta
        quote_field(h.contractor_name),         # 13 Nazwa kontrahenta
        quote_field(h.contractor_street),       # 14 Ulica
        quote_field(h.contractor_city),         # 15 Miasto
        quote_field(h.contractor_postal_code),  # 16 Kod pocztowy
        quote_field(h.contractor_region),       # 17 Województwo / region
        h.field_18,                             # 18 (reserved)
        quote_field(h.contractor_country),      # 19 Kraj
        h.contractor_nip if h.contractor_nip else "",  # 20 NIP kontrahenta
        format_epp_date(h.issue_date),          # 21 Data wystawienia
        format_epp_date(sale),                  # 22 Data sprzedaży
        format_epp_date(receipt),               # 23 Data wpływu
        str(h.flag_24),                         # 24 (flag)
        str(h.flag_25),                         # 25 (flag)
        format_epp_amount(h.net_total),         # 26 Netto
        format_epp_amount(h.vat_total),         # 27 VAT
        format_epp_amount(h.gross_total),       # 28 Brutto
        format_epp_amount(h.field_29),          # 29 (optional)
        h.payment_method,                       # 30 Forma płatności
        format_epp_amount(h.amount_paid),       # 31 Zapłacono
        h.field_32,                             # 32 (reserved)
        format_epp_date(due),                   # 33 Termin płatności
        format_epp_amount(h.field_34),          # 34 (optional)
        format_epp_amount(h.field_35),          # 35 (optional)
        str(h.flag_36),                         # 36
        str(h.flag_37),                         # 37
        str(h.flag_38),                         # 38
        h.field_39,                             # 39
        h.field_40,                             # 40
        h.field_41,                             # 41
        h.field_42,                             # 42
        h.field_43,                             # 43
        quote_field(h.currency),                # 44 Waluta
        f"{h.exchange_rate:.4f}",               # 45 Kurs waluty
        h.field_46,                             # 46
        h.field_47,                             # 47
        h.field_48,                             # 48
        str(h.flag_49),                         # 49
        str(h.flag_50),                         # 50
        str(h.flag_51),                         # 51
    ]
    return ",".join(fields)


def _build_vat_line(row) -> str:
    """Render one [ZAWARTOSC] record (Table 4/5) – single VAT-rate row."""
    return ",".join([
        quote_field(row.vat_symbol),        # 1  Symbol stawki
        format_epp_amount(row.vat_rate),    # 2  Stawka % (may be -5.00 for "00")
        format_epp_amount(row.net_amount),  # 3  Netto
        format_epp_amount(row.vat_amount),  # 4  VAT
        format_epp_amount(row.gross_amount),# 5  Brutto
    ])


def generate_epp(
    info: EPPInfo,
    documents: List[EPPDocument],
) -> str:
    """Build the full EPP file content as a Python string (Unicode).

    Use :func:`generate_epp_bytes` if you need Windows-1250 encoded bytes
    ready for file output.
    """
    lines: list[str] = []

    # ── [INFO] – always first ────────────────────────────────────────────
    lines.append("[INFO]")
    lines.append(_build_info_line(info))

    # ── Per-document: [NAGLOWEK] + [ZAWARTOSC] ──────────────────────────
    for doc in documents:
        lines.append("[NAGLOWEK]")
        lines.append(_build_header_line(doc))

        lines.append("[ZAWARTOSC]")
        for vat_row in doc.vat_rows:
            lines.append(_build_vat_line(vat_row))

    # File must end with a blank line
    lines.append("")

    return "\n".join(lines)


def generate_epp_bytes(
    info: EPPInfo,
    documents: List[EPPDocument],
) -> bytes:
    """Build the EPP file and encode it to Windows-1250 bytes."""
    text = generate_epp(info, documents)
    logger.info(
        "Generated EPP file: %d document(s), %d bytes (Unicode)",
        len(documents),
        len(text),
    )
    return encode_win1250(text)
