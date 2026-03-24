"""Celery task for background Rewizor GT EPP generation."""

from src.workers.celery_app import celery_app


@celery_app.task(name="report.rewizor_export", bind=True, max_retries=2)
def rewizor_export_task(self, file_path: str) -> dict:
    """Run Rewizor OCR + EPP generation asynchronously.

    Document type is auto-detected by OCR from the document content.
    Returns a dict with ``epp_filename`` and base64-encoded ``epp_b64``
    so the result can be retrieved via Celery's result backend.
    """
    import base64

    from src.services.rewizor_service import process_and_export

    try:
        result = process_and_export(file_path)
        return {
            "epp_filename": result["epp_filename"],
            "epp_b64": base64.b64encode(result["epp_bytes"]).decode("ascii"),
            "invoice_data": result["invoice_data"],
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)
