"""Shared pytest fixtures."""

import os
import pytest

# Ensure test environment variables are set before any imports touch them.
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "rewizor_db")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "root")
os.environ.setdefault("DB_PORT", "5435")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")


@pytest.fixture
def sample_invoice_data():
    """Minimal invoice dict as returned by OCR service — Polish supplier, 23% VAT."""
    return {
        "doc_type": "FZ",
        "invoice_number": "FV/2026/001",
        "issue_date": "2026-03-15",
        "sale_date": "2026-03-15",
        "receipt_date": "2026-03-16",
        "payment_due_date": "2026-04-15",
        "payment_method": "przelew",
        "currency": "PLN",
        "exchange_rate": 1.0,
        "net_amount": 1000.00,
        "vat_amount": 230.00,
        "gross_amount": 1230.00,
        "vendor": "Supplier Sp. z o.o.",
        "customer": "Buyer S.A.",
        "contractor_nip": "1234567890",
        "contractor_name": "Supplier Sp. z o.o.",
        "contractor_street": "ul. Testowa 1",
        "contractor_city": "Warszawa",
        "contractor_postal_code": "00-001",
        "contractor_country": "PL",
        "is_correction": False,
        "vat_breakdown": [
            {
                "rate": 23.0,
                "symbol": "23",
                "net": 1000.00,
                "vat": 230.00,
                "gross": 1230.00,
            }
        ],
    }


@pytest.fixture
def sample_foreign_invoice_data():
    """Invoice from a foreign (EU) supplier with 0 VAT — reverse charge."""
    return {
        "doc_type": "FZ",
        "invoice_number": "INV-2026-100",
        "issue_date": "2026-03-10",
        "sale_date": "2026-03-10",
        "receipt_date": "2026-03-12",
        "payment_due_date": "2026-04-10",
        "payment_method": "przelew",
        "currency": "EUR",
        "exchange_rate": 4.3215,
        "net_amount": 5000.00,
        "vat_amount": 0.00,
        "gross_amount": 5000.00,
        "vendor": "GmbH Berlin",
        "customer": "Buyer S.A.",
        "contractor_nip": "DE123456789",
        "contractor_name": "GmbH Berlin",
        "contractor_street": "Berliner Str. 10",
        "contractor_city": "Berlin",
        "contractor_postal_code": "10115",
        "contractor_country": "DE",
        "is_correction": False,
        "vat_breakdown": [
            {
                "rate": 0.0,
                "symbol": "oo",
                "net": 5000.00,
                "vat": 0.00,
                "gross": 5000.00,
            }
        ],
    }


@pytest.fixture
def sample_correction_invoice_data():
    """Correction (credit note) invoice."""
    return {
        "doc_type": "FZK",
        "invoice_number": "FVK/2026/001",
        "issue_date": "2026-03-20",
        "sale_date": "2026-03-15",
        "receipt_date": "2026-03-21",
        "payment_due_date": "2026-04-20",
        "payment_method": "przelew",
        "currency": "PLN",
        "exchange_rate": 1.0,
        "net_amount": -200.00,
        "vat_amount": -46.00,
        "gross_amount": -246.00,
        "vendor": "Supplier Sp. z o.o.",
        "customer": "Buyer S.A.",
        "contractor_nip": "1234567890",
        "contractor_name": "Supplier Sp. z o.o.",
        "contractor_street": "ul. Testowa 1",
        "contractor_city": "Warszawa",
        "contractor_postal_code": "00-001",
        "contractor_country": "PL",
        "is_correction": True,
        "corrected_doc_number": "FV/2026/001",
        "corrected_doc_date": "2026-03-15",
        "vat_breakdown": [
            {
                "rate": 23.0,
                "symbol": "23",
                "net": -200.00,
                "vat": -46.00,
                "gross": -246.00,
            }
        ],
    }


@pytest.fixture
def sample_oss_invoice_data():
    """EU supplier charging Polish VAT via OSS (e.g. Surfshark).

    No reverse charge — transaction_type stays 0 (domestic), VAT symbol
    is "23" just like a Polish invoice, but contractor country is foreign.
    """
    return {
        "doc_type": "FZ",
        "invoice_number": "SHARK 125738",
        "issue_date": "2026-03-09",
        "sale_date": "2026-03-09",
        "receipt_date": "2026-03-09",
        "payment_due_date": "2026-03-23",
        "payment_method": "przelew",
        "currency": "PLN",
        "exchange_rate": 1.0,
        "net_amount": 200.85,
        "vat_amount": 46.20,
        "gross_amount": 247.05,
        "vendor": "Surfshark B.V.",
        "customer": "Exact Solution Electronics Sp.Z O.O",
        "contractor_nip": "NL862287339B01",
        "contractor_name": "Surfshark B.V.",
        "contractor_street": "Kabelweg 57",
        "contractor_city": "Amsterdam",
        "contractor_postal_code": "1014BA",
        "contractor_country": "NL",
        "transaction_id": "eda1f5e6-4330-447e-91d6-a4f4796a97a2",
        "is_correction": False,
        "vat_breakdown": [
            {
                "rate": 23.0,
                "symbol": "23",
                "net": 200.85,
                "vat": 46.20,
                "gross": 247.05,
            }
        ],
    }
