"""Tests for the FastAPI endpoints (no DB / OCR – mocked)."""

import io
from unittest.mock import MagicMock, patch

import pytest

# The app imports ocr_service which depends on fitz (PyMuPDF).
pytest.importorskip("fitz", reason="PyMuPDF not installed")

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


class TestHealthEndpoint:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestUploadEndpoint:
    def test_no_file_returns_422(self):
        resp = client.post("/api/v1/rewizor/upload")
        assert resp.status_code == 422

    def test_empty_filename_returns_400(self):
        resp = client.post(
            "/api/v1/rewizor/upload",
            files={"file": ("", b"content", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_unsupported_extension_returns_400(self):
        resp = client.post(
            "/api/v1/rewizor/upload",
            files={"file": ("test.docx", b"content", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    def test_empty_file_returns_400(self):
        resp = client.post(
            "/api/v1/rewizor/upload",
            files={"file": ("test.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    @patch("src.api.rewizor_api.process_and_export")
    @patch("src.api.rewizor_api.cleanup_upload")
    def test_successful_upload(self, mock_cleanup, mock_process):
        mock_process.return_value = {
            "epp_bytes": b"[INFO]\ntest",
            "epp_filename": "test.epp",
            "invoice_data": {},
            "doc_type": "FZ",
        }
        resp = client.post(
            "/api/v1/rewizor/upload",
            files={"file": ("invoice.pdf", b"%PDF-fake", "application/pdf")},
        )
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="test.epp"'
        assert resp.content == b"[INFO]\ntest"
        mock_cleanup.assert_called_once()

    @patch("src.api.rewizor_api.process_and_export")
    @patch("src.api.rewizor_api.cleanup_upload")
    def test_ocr_failure_returns_422(self, mock_cleanup, mock_process):
        from src.services.ocr_service import OCRExtractionError
        mock_process.side_effect = OCRExtractionError("parse failed")
        resp = client.post(
            "/api/v1/rewizor/upload",
            files={"file": ("invoice.pdf", b"%PDF-fake", "application/pdf")},
        )
        assert resp.status_code == 422
        assert "OCR extraction failed" in resp.json()["detail"]
        mock_cleanup.assert_called_once()


class TestExportEndpoint:
    @patch("src.api.rewizor_api.export_from_db")
    def test_no_documents_returns_404(self, mock_export):
        mock_export.return_value = {"count": 0, "epp_bytes": b"", "epp_filename": ""}
        resp = client.post("/api/v1/rewizor/export?status=PENDING")
        assert resp.status_code == 404

    @patch("src.api.rewizor_api.export_from_db")
    def test_successful_export(self, mock_export):
        mock_export.return_value = {
            "count": 2,
            "epp_bytes": b"[INFO]\nbatch",
            "epp_filename": "rewizor_export.epp",
        }
        resp = client.post("/api/v1/rewizor/export?status=PENDING")
        assert resp.status_code == 200
        assert resp.content == b"[INFO]\nbatch"

    def test_invalid_doc_type_returns_400(self):
        resp = client.post("/api/v1/rewizor/export?doc_type=INVALID")
        assert resp.status_code == 400
        assert "Invalid doc_type" in resp.json()["detail"]
