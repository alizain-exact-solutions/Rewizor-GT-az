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
os.environ.setdefault("EPP_SENDER_NAME", "Test Sender")
os.environ.setdefault("EPP_COMPANY_NAME", "Test Corp")
os.environ.setdefault("EPP_COMPANY_NIP", "PL0000000000")


@pytest.fixture
def sample_invoice_data():
    """Minimal invoice dict as returned by OCR service."""
    return {
        "doc_type": "FZ",
        "invoice_number": "FV/2026/001",
        "issue_date": "2026-03-15",
        "sale_date": "2026-03-15",
        "receipt_date": "2026-03-16",
        "payment_due_date": "2026-04-15",
        "payment_method": "P",
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
    """Invoice from a foreign (non-Polish) supplier with 0 VAT."""
    return {
        "doc_type": "FZ",
        "invoice_number": "INV-2026-100",
        "issue_date": "2026-03-10",
        "sale_date": "2026-03-10",
        "receipt_date": "2026-03-12",
        "payment_due_date": "2026-04-10",
        "payment_method": "P",
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
                "symbol": "np",
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
        "payment_method": "P",
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
