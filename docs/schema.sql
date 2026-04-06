-- Rewizor project database schema
-- Get-Content docs\schema.sql | docker compose exec -T db psql -U postgres -d rewizor_db

CREATE TABLE IF NOT EXISTS documents (
    document_id SERIAL PRIMARY KEY,
    invoice_number TEXT,
    total_amount DECIMAL,
    currency TEXT DEFAULT 'PLN',
    vat_amount DECIMAL,
    gross_amount DECIMAL,
    net_amount DECIMAL,
    date DATE,
    vendor TEXT,
    customer TEXT,
    contractor_nip TEXT,
    contractor_name TEXT,
    contractor_street TEXT,
    contractor_city TEXT,
    contractor_postal_code TEXT,
    contractor_country TEXT DEFAULT 'PL',
    supplier_region TEXT,
    supplier_country_code TEXT,
    doc_type TEXT DEFAULT 'FZ',
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents (doc_type);
