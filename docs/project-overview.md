## Rewizor GT Export API - Project Overview

### What this project does (end-to-end)
Rewizor GT Export API turns accounting documents into Rewizor GT-ready EDI++ (.epp) files.
It is built for Polish finance workflows where invoice data must be extracted, standardized, and imported into Rewizor GT.

Typical flow:
- Upload PDF or image (invoice, correction, bank statement, etc.)
- OCR extracts structured fields (amounts, dates, VAT, NIP, parties)
- Data is classified, validated, and stored in the database
- An EPP file is generated and returned for direct import into Rewizor GT

Alternative flow:
- Export EPP files in batch from documents already stored in the database

### Tech stack
- Backend: Python 3.12 + FastAPI + Uvicorn
- OCR and extraction: OpenAI Vision API (gpt-4o)
- Data processing: Pydantic models and custom EPP mapping
- Database: PostgreSQL with Alembic migrations
- Deployment: Docker + Docker Compose
- Storage: Local filesystem for uploads (temporary)

### Key features
- Supports all 12 Rewizor GT document types (FZ, FS, KZ, KS, FZK, FSK, KZK, KSK, WB, RK, PK, DE)
- VAT and reverse-charge logic for EU and non-EU suppliers
- Rewizor-compliant EPP output (Windows-1250 encoded)
- Rate limiting and file size controls for safer API use

### External dependencies and integrations
- OpenAI API (OCR extraction of document data)
- PostgreSQL (document storage)
- Docker image: postgres:15-alpine

### Data model (high level)
- Documents table stores extracted invoice data, status, and classification
- Status tracking: PENDING -> EXPORTED
- Core fields include amounts, VAT, dates, contractor details, and doc type

### API surface (summary)
- POST /api/v1/rewizor/upload
	- Upload document, run OCR, return .epp file
- POST /api/v1/rewizor/export
	- Export .epp from stored documents by ID or status
- GET /health
	- Service health check

### Deployment and operations
- Default API port: 8001
- Database port (Docker): 5435 -> 5432
- Environment configuration in .env (API key, DB credentials, EPP sender details)
- Upload size limit: 20 MB
- Rate limits: 10/min for upload, 30/min for export

### Notes for stakeholders
- The system is designed for accounting teams using Rewizor GT
- Output files are directly importable into Rewizor GT without manual editing
- Data quality depends on OCR clarity; poor scans can reduce accuracy
- Sensitive values (API key, DB password) are configured via environment variables
