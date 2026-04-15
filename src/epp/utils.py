"""
Rewizor GT EDI++ utility helpers (v1.12 spec).

Date formatting (``yyyymmdd000000``), amount formatting (4 decimal places),
field encoding, and CRLF-joined line assembly for EPP files.
"""

from datetime import date, datetime
from typing import Any, Iterable, Optional, Union

# Sentinel marker: use to emit NOTHING between two commas (i.e. ``,,``).
# This is distinct from ``'""'`` (quoted empty string) — the EDI++ v1.12
# spec requires bare ``,,`` for empty optional fields and reserves quoted
# empty strings for the cases where the grammar demands a text token.
EMPTY = ""


def format_epp_date(value: Optional[Union[str, date, datetime]]) -> str:
    """Convert a date to EDI++ format ``yyyymmdd000000`` (time zeroed).

    Accepts:
      - ``datetime.date`` / ``datetime.datetime``
      - ISO-style strings: ``YYYY-MM-DD``, ``YYYY/MM/DD``, ``DD-MM-YYYY``, etc.
      - ``None`` / empty → empty string (field left blank in EPP)

    >>> format_epp_date("2026-03-19")
    '20260319000000'
    """
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.strftime("%Y%m%d") + "000000"
    if isinstance(value, date):
        return value.strftime("%Y%m%d") + "000000"

    text = str(value).strip()
    if not text:
        return ""
    if "T" in text:
        text = text.split("T", 1)[0]
    elif " " in text:
        text = text.split(" ", 1)[0]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
                "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
                "%Y%m%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y%m%d") + "000000"
        except ValueError:
            continue

    return ""


def format_epp_datetime(value: Optional[Union[str, datetime]] = None) -> str:
    """Format a *real* timestamp as ``yyyymmddhhmmss`` (time preserved).

    Used exclusively for [INFO] field 20 (file generation timestamp).
    ``None`` → current UTC time.
    """
    if value is None:
        dt = datetime.now()
    elif isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                dt = datetime.now()
    return dt.strftime("%Y%m%d%H%M%S")


def format_epp_amount(value: Optional[Union[int, float, str]]) -> str:
    """Format a numeric amount for EPP: 4 decimal places, dot separator, no thousands sep.

    The EDI++ 1.12 spec requires 4-decimal amounts on every numeric field.

    >>> format_epp_amount(1234.5)
    '1234.5000'
    >>> format_epp_amount(None)
    '0.0000'
    """
    if value is None:
        return "0.0000"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def format_epp_int(value: Optional[Union[int, float, str]]) -> str:
    """Format a byte/boolean/integer field as a bare integer.

    ``None`` / non-numeric → ``"0"``.
    """
    if value is None:
        return "0"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def quote_field(value: Optional[str]) -> str:
    """Wrap a text field in double-quotes.

    Empty / ``None`` values produce an empty **quoted** string ``""``.
    Internal double-quotes are escaped by doubling them (EDI++ rule).

    >>> quote_field('FV/001/2026')
    '"FV/001/2026"'
    >>> quote_field('')
    '""'
    """
    if value is None or value == "":
        return '""'
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


def quote_or_empty(value: Optional[str]) -> str:
    """Quoted text when present, bare empty when absent.

    This emits nothing between commas (``,,``) for unfilled optional text
    fields — the EDI++ 1.12 spec requirement for optional text slots.

    >>> quote_or_empty("Amsterdam")
    '"Amsterdam"'
    >>> quote_or_empty(None)
    ''
    """
    if value is None or value == "":
        return EMPTY
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


def build_line(fields: Iterable[Any]) -> str:
    """Join pre-formatted field tokens with commas to produce one EPP record.

    Each element must already be a string in its final wire format
    (quoted text, 4-decimal amount, bare int, or :data:`EMPTY`).

    Example::

        build_line(['"FZ"', '1', '"SHARK 125738"', EMPTY, '200.8500'])
        → '"FZ",1,"SHARK 125738",,200.8500'
    """
    return ",".join("" if f is None else str(f) for f in fields)


def join_epp_lines(lines: Iterable[str]) -> str:
    """Join EPP lines with CRLF and end with a trailing blank CRLF line.

    The EDI++ spec mandates Windows CRLF and a trailing blank line —
    Unix LF or a missing trailing newline cause Rewizor to truncate or
    crash during import.
    """
    body = "\r\n".join(lines)
    # Guarantee exactly one trailing blank line (i.e. the content ends with
    # CRLF-CRLF). ``split('\r\n')`` after writing the buffer will see an
    # empty final element.
    if not body.endswith("\r\n"):
        body += "\r\n"
    body += "\r\n"
    return body


def encode_win1250(text: str) -> bytes:
    """Encode a full EPP string to Windows-1250 bytes.

    Characters that cannot be mapped are replaced with ``?``.
    """
    return text.encode("cp1250", errors="replace")
