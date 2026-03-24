"""
Rewizor GT EDI++ utility helpers.

Date formatting (yyyymmdd000000) and field encoding for EPP files.
"""

from datetime import date, datetime
from typing import Optional, Union


def format_epp_date(value: Optional[Union[str, date, datetime]]) -> str:
    """Convert a date to EDI++ format ``yyyymmdd000000`` (time zeroed).

    Accepts:
      - ``datetime.date`` / ``datetime.datetime``
      - ISO-style strings: ``YYYY-MM-DD``, ``YYYY/MM/DD``, ``DD-MM-YYYY``, etc.
      - ``None`` → empty string (field left blank in EPP)

    >>> format_epp_date("2026-03-19")
    '20260319000000'
    """
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.strftime("%Y%m%d") + "000000"
    if isinstance(value, date):
        return value.strftime("%Y%m%d") + "000000"

    # String – try common date formats
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    elif " " in text:
        text = text.split(" ", 1)[0]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
                "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y%m%d") + "000000"
        except ValueError:
            continue

    return ""


def format_epp_amount(value: Optional[Union[int, float, str]]) -> str:
    """Format a numeric amount for EPP: dot decimal, 2 places, no thousands sep.

    >>> format_epp_amount(1234.5)
    '1234.50'
    >>> format_epp_amount(None)
    '0.00'
    """
    if value is None:
        return "0.00"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def quote_field(value: Optional[str]) -> str:
    """Wrap a text field in double-quotes for safe comma-separated output.

    Empty / None values produce an empty quoted string ``""``.
    Internal double-quotes are escaped by doubling them.

    >>> quote_field('FV/001/2026')
    '"FV/001/2026"'
    """
    if not value:
        return '""'
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


def encode_win1250(text: str) -> bytes:
    """Encode a full EPP string to Windows-1250 bytes.

    Characters that cannot be mapped are replaced with ``?``.
    """
    return text.encode("cp1250", errors="replace")
