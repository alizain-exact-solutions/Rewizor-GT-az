"""Tests for src.epp.mapper – invoice dict → EPP document conversion."""

from src.epp.mapper import map_invoice_to_epp
from src.epp.classifier import classify_supplier


class TestMapInvoiceToEpp:
    def test_basic_purchase_invoice(self, sample_invoice_data):
        doc = map_invoice_to_epp(sample_invoice_data)
        h = doc.header
        assert h.doc_type == "FZ"
        assert h.rodzaj_rejestru == 1  # purchase register
        assert h.rodzaj_dokumentu == 0  # normal (not correction)
        assert h.doc_number == "FV/2026/001"
        assert h.net_total == 1000.00
        assert h.vat_total == 230.00
        assert h.gross_total == 1230.00
        assert h.currency == "PLN"
        assert h.exchange_rate == 1.0
        assert h.contractor_nip == "1234567890"
        assert h.contractor_name == "Supplier Sp. z o.o."
        assert h.contractor_country == "PL"
        assert len(doc.vat_rows) == 1
        assert doc.vat_rows[0].vat_symbol == "23"
        assert doc.vat_rows[0].vat_rate == 23.0

    def test_foreign_invoice_exempt(self, sample_foreign_invoice_data):
        doc = map_invoice_to_epp(sample_foreign_invoice_data)
        h = doc.header
        assert h.currency == "EUR"
        assert h.exchange_rate == 4.3215  # preserved at 4 decimal places
        assert h.flag_50 == 1  # reverse charge flag
        assert h.kod_transakcji == "IU"  # import usług
        # Foreign supplier with 0 VAT → "np" (nie podlega)
        assert len(doc.vat_rows) == 1
        assert doc.vat_rows[0].vat_symbol == "np"
        assert doc.vat_rows[0].vat_rate == -1.0

    def test_correction_invoice(self, sample_correction_invoice_data):
        doc = map_invoice_to_epp(sample_correction_invoice_data)
        h = doc.header
        assert h.doc_type == "FZK"
        assert h.rodzaj_dokumentu == 1  # correction

    def test_doc_type_override(self, sample_invoice_data):
        doc = map_invoice_to_epp(sample_invoice_data, doc_type="FS")
        assert doc.header.doc_type == "FS"
        assert doc.header.rodzaj_rejestru == 2  # sales register

    def test_sales_invoice_register(self, sample_invoice_data):
        sample_invoice_data["doc_type"] = "FS"
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.rodzaj_rejestru == 2

    def test_non_vat_doc_type(self, sample_invoice_data):
        sample_invoice_data["doc_type"] = "WB"
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.doc_type == "WB"
        assert doc.header.rodzaj_rejestru == 0  # other register
        assert len(doc.vat_rows) == 1
        assert doc.vat_rows[0].vat_symbol == "0"

    def test_missing_gross_calculated(self, sample_invoice_data):
        sample_invoice_data["gross_amount"] = 0
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.gross_total == 1230.00  # net + vat

    def test_contractor_symbol_from_name(self, sample_invoice_data):
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.contractor_symbol == "SUPPLIER_SP._Z_O.O."[:40]

    def test_unknown_doc_type_defaults_to_fz(self, sample_invoice_data):
        sample_invoice_data["doc_type"] = "BOGUS"
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.doc_type == "FZ"

    def test_no_vat_breakdown_infers_single_row(self, sample_invoice_data):
        del sample_invoice_data["vat_breakdown"]
        doc = map_invoice_to_epp(sample_invoice_data)
        assert len(doc.vat_rows) == 1
        assert doc.vat_rows[0].vat_rate == 23.0

    def test_db_row_minimal(self):
        """Simulate a minimal DB row (no vat_breakdown, no doc_type)."""
        row = {
            "document_id": 1,
            "invoice_number": "DB-001",
            "net_amount": 500.0,
            "vat_amount": 115.0,
            "gross_amount": 615.0,
            "date": "2026-01-15",
            "vendor": "DB Vendor",
            "contractor_nip": "9876543210",
            "contractor_name": "DB Vendor",
            "currency": "PLN",
        }
        doc = map_invoice_to_epp(row, doc_type="FZ")
        assert doc.header.doc_type == "FZ"
        assert doc.header.net_total == 500.0

    def test_payment_method_valid(self, sample_invoice_data):
        sample_invoice_data["payment_method"] = "G"
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.payment_method == "G"

    def test_payment_method_foreign_cleared(self, sample_foreign_invoice_data):
        doc = map_invoice_to_epp(sample_foreign_invoice_data)
        assert doc.header.payment_method == ""


class TestClassifySupplier:
    """Tests for the layered supplier classifier (VAT → code → text → currency)."""

    # ── Layer 1: VAT/NIP prefix ──────────────────────────────────────────
    def test_vat_prefix_pl(self):
        r = classify_supplier({"contractor_nip": "PL1234567890"})
        assert r["type"] == "PL" and r["code"] == "PL"

    def test_vat_prefix_de(self):
        r = classify_supplier({"contractor_nip": "DE298765432"})
        assert r["type"] == "EU" and r["code"] == "DE"

    def test_vat_prefix_gb(self):
        r = classify_supplier({"contractor_nip": "GB123456789"})
        assert r["type"] == "NON_EU" and r["code"] == "GB"

    def test_vat_prefix_fr(self):
        r = classify_supplier({"contractor_nip": "FR12345678901"})
        assert r["type"] == "EU" and r["code"] == "FR"

    # ── Layer 2: ISO country code ────────────────────────────────────────
    def test_country_code_pl(self):
        r = classify_supplier({"contractor_country": "PL"})
        assert r["type"] == "PL"

    def test_country_code_polska(self):
        r = classify_supplier({"contractor_country": "Polska"})
        assert r["type"] == "PL"

    def test_country_code_de(self):
        r = classify_supplier({"contractor_country": "DE"})
        assert r["type"] == "EU" and r["code"] == "DE"

    def test_country_code_us(self):
        r = classify_supplier({"contractor_country": "US"})
        assert r["type"] == "NON_EU" and r["code"] == "US"

    def test_country_code_sg(self):
        r = classify_supplier({"contractor_country": "SG"})
        assert r["type"] == "NON_EU" and r["code"] == "SG"

    def test_country_code_gb(self):
        r = classify_supplier({"contractor_country": "GB"})
        assert r["type"] == "NON_EU" and r["code"] == "GB"

    # ── Layer 3: Text matching (messy OCR) ───────────────────────────────
    def test_text_match_united_states(self):
        r = classify_supplier({"contractor_city": "Seattle", "contractor_country": "United States"})
        assert r["type"] == "NON_EU"

    def test_text_match_germany(self):
        r = classify_supplier({"contractor_city": "Berlin, Germany"})
        assert r["type"] == "EU" and r["code"] == "DE"

    def test_text_match_uk(self):
        r = classify_supplier({"contractor_city": "London", "contractor_country": "United Kingdom"})
        assert r["type"] == "NON_EU" and r["code"] == "GB"

    def test_text_match_holland(self):
        r = classify_supplier({"contractor_country": "Holland"})
        assert r["type"] == "EU" and r["code"] == "NL"

    def test_text_match_czechia(self):
        r = classify_supplier({"contractor_country": "Czechia"})
        assert r["type"] == "EU" and r["code"] == "CZ"

    def test_text_match_switzerland(self):
        r = classify_supplier({"contractor_country": "Switzerland"})
        assert r["type"] == "NON_EU" and r["code"] == "CH"

    # ── Layer 4: Currency fallback ───────────────────────────────────────
    def test_currency_pln(self):
        r = classify_supplier({"currency": "PLN"})
        assert r["type"] == "PL"

    def test_currency_usd(self):
        r = classify_supplier({"currency": "USD"})
        assert r["type"] == "NON_EU"

    # ── Layer 5: Polish NIP (10 digits, no prefix) ───────────────────────
    def test_polish_nip_digits_only(self):
        r = classify_supplier({"contractor_nip": "1234567890", "currency": "EUR"})
        assert r["type"] == "PL"

    # ── Priority: VAT prefix beats country code ─────────────────────────
    def test_vat_prefix_overrides_country(self):
        """NIP says DE but country says US — VAT prefix wins."""
        r = classify_supplier({"contractor_nip": "DE123456789", "contractor_country": "US"})
        assert r["type"] == "EU" and r["code"] == "DE"

    # ── Edge: empty invoice ──────────────────────────────────────────────
    def test_empty_invoice_defaults_pln(self):
        r = classify_supplier({})
        assert r["type"] == "PL"  # currency defaults to PLN


class TestEuVsNonEuMapping:
    """Tests for EU vs NON-EU transaction classification in EPP output."""

    def test_eu_supplier_gets_iu_code(self, sample_foreign_invoice_data):
        sample_foreign_invoice_data["contractor_country"] = "DE"
        doc = map_invoice_to_epp(sample_foreign_invoice_data)
        assert doc.header.kod_transakcji == "IU"
        assert doc.header.flag_50 == 1

    def test_non_eu_supplier_gets_iu_code(self, sample_foreign_invoice_data):
        sample_foreign_invoice_data["contractor_country"] = "US"
        doc = map_invoice_to_epp(sample_foreign_invoice_data)
        assert doc.header.kod_transakcji == "IU"
        assert doc.header.flag_50 == 1

    def test_polish_supplier_no_transaction_code(self, sample_invoice_data):
        doc = map_invoice_to_epp(sample_invoice_data)
        assert doc.header.kod_transakcji == ""
        assert doc.header.flag_50 == 0

    def test_eu_supplier_vat_symbol_np(self, sample_foreign_invoice_data):
        sample_foreign_invoice_data["contractor_country"] = "FR"
        doc = map_invoice_to_epp(sample_foreign_invoice_data)
        assert doc.vat_rows[0].vat_symbol == "np"

    def test_non_eu_supplier_vat_symbol_np(self, sample_foreign_invoice_data):
        sample_foreign_invoice_data["contractor_country"] = "SG"
        doc = map_invoice_to_epp(sample_foreign_invoice_data)
        assert doc.vat_rows[0].vat_symbol == "np"
