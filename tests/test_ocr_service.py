"""Tests for src.services.ocr_service – parsing/normalization (no API calls)."""

import pytest

# fitz (PyMuPDF) may not be installed in the test environment (it runs in Docker).
# Skip the entire module if the import chain fails.
pytest.importorskip("fitz", reason="PyMuPDF not installed")

from src.services.ocr_service import OCRExtractionError, RewizorOCRService


class TestParseJson:
    def test_plain_json(self):
        data = RewizorOCRService._parse_json('{"key": "value"}')
        assert data == {"key": "value"}

    def test_markdown_fenced_json(self):
        raw = '```json\n{"key": "value"}\n```'
        data = RewizorOCRService._parse_json(raw)
        assert data == {"key": "value"}

    def test_generic_fenced(self):
        raw = '```\n{"key": "value"}\n```'
        data = RewizorOCRService._parse_json(raw)
        assert data == {"key": "value"}

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            RewizorOCRService._parse_json("not json at all")


class TestNormalize:
    def test_amounts_normalized(self):
        data = {
            "net_amount": "1000.50",
            "vat_amount": "230.115",
            "gross_amount": 1230.62,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["net_amount"] == 1000.50
        assert result["vat_amount"] == 230.12  # abs + round
        assert result["gross_amount"] == 1230.62

    def test_dates_normalized(self):
        data = {
            "issue_date": "15-03-2026",
            "sale_date": "2026/03/15",
            "receipt_date": None,
            "payment_due_date": "2026-04-15",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["issue_date"] == "2026-03-15"
        assert result["sale_date"] == "2026-03-15"
        assert result["receipt_date"] is None
        assert result["date"] == "2026-03-15"

    def test_nip_cleaned(self):
        data = {
            "contractor_nip": "PL 123-456-78-90",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["contractor_nip"] == "1234567890"

    def test_country_uppercased(self):
        data = {
            "contractor_country": " pl ",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["contractor_country"] == "PL"

    def test_currency_uppercased(self):
        data = {
            "currency": "eur",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["currency"] == "EUR"

    def test_payment_method_mapped(self):
        data = {
            "payment_method": "przelew",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["payment_method"] == "P"

    def test_payment_method_gotowka(self):
        data = {
            "payment_method": "gotówka",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["payment_method"] == "G"

    def test_invalid_doc_type_defaults_to_fz(self):
        data = {
            "doc_type": "NOPE",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
        }
        result = RewizorOCRService._normalize(data)
        assert result["doc_type"] == "FZ"

    def test_exchange_rate_preserved(self):
        data = {
            "exchange_rate": "4.3215",
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["exchange_rate"] == 4.3215

    def test_vat_breakdown_amounts_normalized(self):
        data = {
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
            "vat_breakdown": [
                {"rate": "23", "net": "100.5", "vat": "23.115", "gross": "123.62"},
            ],
        }
        result = RewizorOCRService._normalize(data)
        row = result["vat_breakdown"][0]
        assert row["rate"] == 23.0
        assert row["net"] == 100.50
        assert row["vat"] == 23.12

    def test_is_correction_coerced_to_bool(self):
        data = {
            "is_correction": 0,
            "net_amount": 0, "vat_amount": 0, "gross_amount": 0,
            "doc_type": "FZ",
        }
        result = RewizorOCRService._normalize(data)
        assert result["is_correction"] is False


class TestOCRExtractionError:
    def test_is_exception(self):
        assert issubclass(OCRExtractionError, Exception)

    def test_message(self):
        err = OCRExtractionError("test error")
        assert str(err) == "test error"


class TestExtractFileValidation:
    def test_missing_file_raises(self):
        """extract() should raise FileNotFoundError for non-existent path."""
        import os
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        svc = RewizorOCRService()
        with pytest.raises(FileNotFoundError):
            svc.extract("/nonexistent/path/invoice.pdf")
