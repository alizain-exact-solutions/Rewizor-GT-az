-- Rewizor project database schema (multi-tenant, shared-schema row-level isolation)
-- Get-Content docs\schema.sql | docker compose exec -T db psql -U postgres -d rewizor_db
--
-- Every business-scoped row carries a `tenant_id VARCHAR(50)` that the host
-- multi-tenant platform provides via the X-Tenant-ID HTTP header. Every
-- tenant-owned table FK-references the central `tenants` table below so
-- typo'd or unknown tenant ids fail at insert time instead of leaving
-- orphaned rows behind.

-- Central tenant identity table — single source of truth, seeded with a
-- 'default' row so single-tenant development works out of the box.
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id VARCHAR(50) PRIMARY KEY,
    display_name TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO tenants (tenant_id, display_name)
VALUES ('default', 'Default (dev / single-tenant)')
ON CONFLICT (tenant_id) DO NOTHING;


CREATE TABLE IF NOT EXISTS documents (
    document_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id),

    -- Identification
    invoice_number TEXT,
    doc_type TEXT DEFAULT 'FZ',
    status TEXT DEFAULT 'PENDING',
    is_correction BOOLEAN DEFAULT FALSE,
    corrected_doc_number TEXT,
    corrected_doc_date DATE,

    -- Dates (Polish accounting cares about all three)
    date DATE,                          -- legacy alias of issue_date; kept for back-compat
    issue_date DATE,                    -- data wystawienia
    sale_date DATE,                     -- data sprzedaży
    receipt_date DATE,                  -- data wpływu
    payment_due_date DATE,              -- termin płatności

    -- Money
    currency TEXT DEFAULT 'PLN',
    exchange_rate DECIMAL(18, 6),
    net_amount DECIMAL(18, 4),
    vat_amount DECIMAL(18, 4),
    gross_amount DECIMAL(18, 4),
    total_amount DECIMAL(18, 4),        -- legacy; equals gross_amount on new rows
    amount_paid DECIMAL(18, 4),
    payment_method TEXT,                -- 'przelew' | 'gotówka' | 'karta' | 'kompensata'

    -- Parties
    vendor TEXT,
    customer TEXT,
    contractor_nip TEXT,
    contractor_name TEXT,
    contractor_street TEXT,
    contractor_city TEXT,
    contractor_postal_code TEXT,
    contractor_region TEXT,
    contractor_country TEXT DEFAULT 'PL',
    customer_nip TEXT,
    supplier_region TEXT,               -- 'PL' | 'EU' | 'NON_EU'
    supplier_country_code TEXT,

    -- Free text
    transaction_id TEXT,
    notes TEXT,

    -- Audit / safety net
    ocr_raw JSONB,                      -- raw OCR payload — re-mappable forever
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_tenant_status ON documents (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_documents_issue_date ON documents (issue_date);


-- Per-rate VAT breakdown for each document (one row per rate).
-- Multi-rate invoices (e.g. mixed 23% goods + 8% transport) lose data
-- when collapsed to totals; this table preserves the per-rate split so
-- exported EPP files match the source invoice exactly.
CREATE TABLE IF NOT EXISTS document_vat_lines (
    line_id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    vat_symbol TEXT NOT NULL,            -- '23' | '8' | '5' | '0' | 'zw' | 'oo' | ...
    vat_rate DECIMAL(8, 4) NOT NULL,
    net_amount DECIMAL(18, 4) NOT NULL DEFAULT 0,
    vat_amount DECIMAL(18, 4) NOT NULL DEFAULT 0,
    gross_amount DECIMAL(18, 4) NOT NULL DEFAULT 0,
    UNIQUE (document_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_vat_lines_document ON document_vat_lines (document_id);


-- Stored EPP exports — every generated .epp is persisted as BYTEA so the
-- frontend can re-download the exact bytes without regeneration drift.
CREATE TABLE IF NOT EXISTS document_exports (
    export_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL
        REFERENCES tenants(tenant_id),
    filename TEXT NOT NULL,
    epp_bytes BYTEA NOT NULL,
    file_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    epp_version TEXT,
    doc_count INTEGER NOT NULL DEFAULT 1,
    export_kind TEXT NOT NULL DEFAULT 'single',     -- 'single' | 'batch' | 'regenerated'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exports_tenant ON document_exports (tenant_id);
CREATE INDEX IF NOT EXISTS idx_exports_tenant_created
    ON document_exports (tenant_id, created_at DESC);


-- Many-to-many: an export bundles one (single/regenerated) or many
-- (batch) documents.
CREATE TABLE IF NOT EXISTS export_documents (
    export_id INTEGER NOT NULL REFERENCES document_exports(export_id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    PRIMARY KEY (export_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_export_documents_document
    ON export_documents (document_id);


-- Per-tenant accounting / sender settings — one row per tenant.
-- Every sender field in the EPP [INFO] and [NAGLOWEK] sections is driven by
-- this row. The frontend manages these values through the "Accounting
-- details" page (GET/PUT /api/v1/accounting/settings).
CREATE TABLE IF NOT EXISTS accounting_settings (
    tenant_id VARCHAR(50) PRIMARY KEY
        REFERENCES tenants(tenant_id),
    -- Sender company
    company_name TEXT NOT NULL,
    company_nip TEXT NOT NULL,
    company_country_code TEXT NOT NULL DEFAULT 'PL',
    company_street TEXT,
    company_city TEXT,
    company_postal_code TEXT,
    -- Subiekt GT branch identifiers
    sender_id_code TEXT,
    sender_short_name TEXT,
    -- Program/warehouse/operator defaults (field 4, 12-14, 19)
    producing_program TEXT DEFAULT 'Subiekt GT',
    warehouse_code TEXT DEFAULT 'MAG',
    warehouse_name TEXT DEFAULT 'Główny',
    warehouse_description TEXT DEFAULT 'Magazyn główny',
    operator_name TEXT DEFAULT 'Szef',
    -- Mapper defaults
    default_payment_term_days INTEGER NOT NULL DEFAULT 14,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
