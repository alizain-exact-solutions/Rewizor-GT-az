"""Tests for src.epp.schemas – Pydantic model validation."""

import pytest
from pydantic import ValidationError

from src.epp.schemas import EPPDocument, EPPHeader, EPPInfo, EPPVatRow


class TestEPPInfo:
    def test_defaults(self):
        info = EPPInfo()
        assert info.version == "1.10"
        assert info.purpose == 0
        assert info.encoding == "1250"

    def test_custom_values(self):
        info = EPPInfo(company_name="Test Corp", company_nip="PL123")
        assert info.company_name == "Test Corp"
        assert info.company_nip == "PL123"


class TestEPPHeader:
    def test_valid_doc_type(self):
        header = EPPHeader(doc_type="FZ", issue_date="2026-03-15")
        assert header.doc_type == "FZ"

    def test_invalid_doc_type_raises(self):
        with pytest.raises(ValidationError, match="Invalid doc_type"):
            EPPHeader(doc_type="INVALID", issue_date="2026-03-15")

    def test_doc_type_normalized_to_uppercase(self):
        header = EPPHeader(doc_type="fz", issue_date="2026-03-15")
        assert header.doc_type == "FZ"

    def test_missing_issue_date_raises(self):
        with pytest.raises(ValidationError, match="issue_date is required"):
            EPPHeader(doc_type="FZ", issue_date="")

    def test_all_12_doc_types_valid(self):
        types = ["FZ", "FS", "KZ", "KS", "FZK", "FSK", "KZK", "KSK",
                 "WB", "RK", "PK", "DE"]
        for dt in types:
            header = EPPHeader(doc_type=dt, issue_date="2026-01-01")
            assert header.doc_type == dt

    def test_defaults(self):
        header = EPPHeader(issue_date="2026-03-15")
        assert header.doc_type == "FZ"
        assert header.rodzaj_rejestru == 1
        assert header.currency == "PLN"
        assert header.exchange_rate == 1.0


class TestEPPVatRow:
    def test_valid_symbol(self):
        row = EPPVatRow(vat_symbol="23", vat_rate=23.0, net_amount=100.0,
                        vat_amount=23.0, gross_amount=123.0)
        assert row.vat_symbol == "23"

    def test_invalid_symbol_raises(self):
        with pytest.raises(ValidationError, match="Invalid vat_symbol"):
            EPPVatRow(vat_symbol="99", vat_rate=99.0)

    def test_all_valid_symbols(self):
        for sym in ["23", "8", "5", "0", "zw", "oo", "np"]:
            row = EPPVatRow(vat_symbol=sym, vat_rate=0.0)
            assert row.vat_symbol == sym

    def test_exempt_symbol(self):
        row = EPPVatRow(vat_symbol="zw", vat_rate=-1.0, net_amount=1000.0,
                        vat_amount=0.0, gross_amount=1000.0)
        assert row.vat_rate == -1.0


class TestEPPDocument:
    def test_composite(self):
        header = EPPHeader(doc_type="FS", issue_date="2026-01-01",
                           rodzaj_rejestru=2)
        rows = [EPPVatRow(vat_symbol="23", vat_rate=23.0, net_amount=100.0,
                          vat_amount=23.0, gross_amount=123.0)]
        doc = EPPDocument(header=header, vat_rows=rows)
        assert doc.header.doc_type == "FS"
        assert len(doc.vat_rows) == 1
