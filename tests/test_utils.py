"""Tests for src.epp.utils and src.core.utils."""

from datetime import date, datetime

from src.core.utils import normalize_amount, normalize_date
from src.epp.utils import encode_win1250, format_epp_amount, format_epp_date, quote_field


# ── format_epp_date ─────────────────────────────────────────────────────────

class TestFormatEppDate:
    def test_iso_string(self):
        assert format_epp_date("2026-03-19") == "20260319000000"

    def test_slash_string(self):
        assert format_epp_date("2026/03/19") == "20260319000000"

    def test_dot_string(self):
        assert format_epp_date("2026.03.19") == "20260319000000"

    def test_dmy_string(self):
        assert format_epp_date("19-03-2026") == "20260319000000"

    def test_datetime_object(self):
        dt = datetime(2026, 3, 19, 14, 30)
        assert format_epp_date(dt) == "20260319000000"

    def test_date_object(self):
        d = date(2026, 3, 19)
        assert format_epp_date(d) == "20260319000000"

    def test_none_returns_empty(self):
        assert format_epp_date(None) == ""

    def test_empty_string_returns_empty(self):
        assert format_epp_date("") == ""

    def test_iso_with_time(self):
        assert format_epp_date("2026-03-19T14:30:00") == "20260319000000"

    def test_invalid_string_returns_empty(self):
        assert format_epp_date("not-a-date") == ""


# ── format_epp_amount ───────────────────────────────────────────────────────

class TestFormatEppAmount:
    def test_float(self):
        assert format_epp_amount(1234.5) == "1234.50"

    def test_integer(self):
        assert format_epp_amount(100) == "100.00"

    def test_zero(self):
        assert format_epp_amount(0) == "0.00"

    def test_none(self):
        assert format_epp_amount(None) == "0.00"

    def test_string_number(self):
        assert format_epp_amount("99.9") == "99.90"

    def test_negative(self):
        assert format_epp_amount(-200.50) == "-200.50"

    def test_invalid_string(self):
        assert format_epp_amount("abc") == "0.00"


# ── quote_field ─────────────────────────────────────────────────────────────

class TestQuoteField:
    def test_normal_string(self):
        assert quote_field("FV/001/2026") == '"FV/001/2026"'

    def test_empty_string(self):
        assert quote_field("") == '""'

    def test_none(self):
        assert quote_field(None) == '""'

    def test_string_with_quotes(self):
        assert quote_field('say "hello"') == '"say ""hello"""'

    def test_string_with_comma(self):
        assert quote_field("a,b") == '"a,b"'


# ── encode_win1250 ──────────────────────────────────────────────────────────

class TestEncodeWin1250:
    def test_ascii(self):
        assert encode_win1250("hello") == b"hello"

    def test_polish_characters(self):
        result = encode_win1250("ąęćłń")
        assert isinstance(result, bytes)
        assert result == "ąęćłń".encode("cp1250")

    def test_unencodable_replaced(self):
        result = encode_win1250("日本語")
        assert b"?" in result


# ── normalize_amount ────────────────────────────────────────────────────────

class TestNormalizeAmount:
    def test_positive_float(self):
        assert normalize_amount(123.456) == 123.46

    def test_negative_preserved(self):
        assert normalize_amount(-99.99) == -99.99

    def test_none_returns_none(self):
        assert normalize_amount(None) is None

    def test_string_number(self):
        assert normalize_amount("100.5") == 100.50

    def test_invalid_returns_none(self):
        assert normalize_amount("abc") is None


# ── normalize_date ──────────────────────────────────────────────────────────

class TestNormalizeDate:
    def test_iso_date(self):
        assert normalize_date("2026-03-19") == "2026-03-19"

    def test_slash_date(self):
        assert normalize_date("2026/03/19") == "2026-03-19"

    def test_dmy(self):
        assert normalize_date("19-03-2026") == "2026-03-19"

    def test_none(self):
        assert normalize_date(None) is None

    def test_empty(self):
        assert normalize_date("") is None

    def test_with_timestamp(self):
        assert normalize_date("2026-03-19T14:30:00") == "2026-03-19"
