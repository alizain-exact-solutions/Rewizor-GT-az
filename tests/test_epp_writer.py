"""Tests for src.epp.epp_writer – EPP file generation."""

from src.epp.epp_writer import generate_epp, generate_epp_bytes
from src.epp.mapper import map_invoice_to_epp
from src.epp.schemas import EPPInfo


def _make_epp(invoice_data, **info_kwargs):
    """Helper: invoice dict → (epp_text, epp_bytes)."""
    doc = map_invoice_to_epp(invoice_data)
    info = EPPInfo(
        generator_name="TestGen",
        company_name="TestCorp",
        company_nip="PL0000000000",
        **info_kwargs,
    )
    text = generate_epp(info, [doc])
    raw = generate_epp_bytes(info, [doc])
    return text, raw


class TestGenerateEpp:
    def test_contains_info_section(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert "[INFO]" in text

    def test_contains_naglowek_section(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert "[NAGLOWEK]" in text

    def test_contains_zawartosc_section(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert "[ZAWARTOSC]" in text

    def test_ends_with_blank_line(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert text.endswith("\n")

    def test_info_line_version(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        info_line = text.split("\n")[1]
        # First field is version "1.10"
        assert info_line.startswith("1.10,")

    def test_info_contains_company(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert '"TestCorp"' in text

    def test_header_doc_type(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        lines = text.split("\n")
        header_line = lines[3]  # [INFO], info_data, [NAGLOWEK], header_data
        assert header_line.startswith('"FZ"')

    def test_header_contains_date(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert "20260315000000" in text

    def test_header_contains_amounts(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert "1000.00" in text
        assert "230.00" in text
        assert "1230.00" in text

    def test_vat_row_values(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        lines = text.split("\n")
        # Find the line after [ZAWARTOSC]
        zaw_idx = lines.index("[ZAWARTOSC]")
        vat_line = lines[zaw_idx + 1]
        assert '"23"' in vat_line
        assert "23.00" in vat_line
        assert "1000.00" in vat_line

    def test_contractor_info(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        assert '"Supplier Sp. z o.o."' in text
        assert "1234567890" in text


class TestGenerateEppBytes:
    def test_returns_bytes(self, sample_invoice_data):
        _, raw = _make_epp(sample_invoice_data)
        assert isinstance(raw, bytes)

    def test_win1250_encoding(self, sample_invoice_data):
        _, raw = _make_epp(sample_invoice_data)
        decoded = raw.decode("cp1250")
        assert "[INFO]" in decoded

    def test_multiple_documents(self, sample_invoice_data, sample_foreign_invoice_data):
        doc1 = map_invoice_to_epp(sample_invoice_data)
        doc2 = map_invoice_to_epp(sample_foreign_invoice_data)
        info = EPPInfo(company_name="Multi")
        text = generate_epp(info, [doc1, doc2])
        assert text.count("[NAGLOWEK]") == 2
        assert text.count("[ZAWARTOSC]") == 2
        # Only one [INFO]
        assert text.count("[INFO]") == 1

    def test_correction_negative_amounts(self, sample_correction_invoice_data):
        text, _ = _make_epp(sample_correction_invoice_data)
        assert "FZK" in text


class TestEppFileStructure:
    def test_section_order(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        lines = text.split("\n")
        sections = [l for l in lines if l.startswith("[")]
        assert sections == ["[INFO]", "[NAGLOWEK]", "[ZAWARTOSC]"]

    def test_comma_separated_fields(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        lines = text.split("\n")
        info_line = lines[1]
        # INFO has 19 fields → 18 commas
        assert info_line.count(",") == 18

    def test_header_51_fields(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        lines = text.split("\n")
        header_line = lines[3]
        # NAGLOWEK has 51 fields → 50 commas
        assert header_line.count(",") == 50

    def test_vat_5_fields(self, sample_invoice_data):
        text, _ = _make_epp(sample_invoice_data)
        lines = text.split("\n")
        zaw_idx = lines.index("[ZAWARTOSC]")
        vat_line = lines[zaw_idx + 1]
        # ZAWARTOSC has 5 fields → 4 commas
        assert vat_line.count(",") == 4
