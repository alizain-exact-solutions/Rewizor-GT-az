# Frontend integration — Rewizor GT EPP service

Generates Rewizor GT EDI++ (`.epp`) files from invoices. Multi-tenant:
every request must identify its tenant via the `X-Tenant-ID` header
(`[A-Za-z0-9_.-]`, 1–50 chars). In dev a missing header falls back to
`"default"`; set `REQUIRE_TENANT_HEADER=1` in prod to reject it instead.

## Core flow

1. Tenant saves sender/company details once (`PUT /accounting/settings`).
2. Upload an invoice (`POST /rewizor/upload`) → get `.epp` bytes back,
   invoice + export are persisted.
3. Browse, re-generate, or re-download later via the endpoints below.

If step 1 is skipped, step 2 returns **412 Precondition Failed** — route
the user to the Accounting Details page on that status.

## Endpoints (all prefixed `/api/v1`)

### Accounting (one-time tenant setup)

| Method | Path | Purpose |
|---|---|---|
| `GET`    | `/accounting/settings` | Pre-fill the form. 404 = empty form, not an error. |
| `PUT`    | `/accounting/settings` | Save/replace settings (idempotent). |
| `DELETE` | `/accounting/settings` | Remove on offboarding. |

Body (PUT): `company_name`, `company_nip` (required, 10 digits; `PL`
prefix stripped), plus optional `company_street`/`company_city`/
`company_postal_code`, `company_country_code` (default `"PL"`),
`sender_id_code`, `sender_short_name`, warehouse/operator overrides,
and `default_payment_term_days` (default `14`).

### Upload & export

**`POST /rewizor/upload`** — the one you care about.
`multipart/form-data` with one `file` part (PDF/PNG/JPG/TIFF/BMP, ≤20 MB).
Returns `application/octet-stream` — the `.epp` bytes with a
`Content-Disposition` filename. Persists both the parsed document and
the generated export; retrieve them later via the endpoints below.

| Status | Meaning |
|---|---|
| 200 | `.epp` bytes in body |
| 400 | missing/empty file, unsupported extension |
| 412 | tenant has no accounting settings — redirect to the form |
| 422 | OCR extraction failed |
| 429 | rate-limited (10/min per IP) |

### Stored documents

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/documents` | Paginated list. Filters: `status` (`PENDING`/`EXPORTED`), `doc_type`, `limit`, `offset`. |
| `GET`  | `/documents/{id}` | Full record with per-rate VAT breakdown. 404 if not this tenant's. |
| `POST` | `/documents/{id}/regenerate` | Produce a **fresh** `.epp` using the tenant's *current* accounting settings. Stores a new export; returns bytes + `X-Export-Id` header. Use this after editing Accounting Details. |

### Stored exports (re-download without drift)

Every `.epp` is kept byte-for-byte in the DB so the user can re-download
the exact file they originally got, even if settings were edited later.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/exports` | Paginated list (metadata only). Filter by `document_id`. Each row includes `export_kind` (`single` / `regenerated`), `sha256`, `doc_count`, and linked `document_ids`. |
| `GET` | `/exports/{id}` | Metadata for one export. |
| `GET` | `/exports/{id}/download` | The stored `.epp` bytes. Response carries `Content-Disposition`, `Content-Length`, `X-Content-SHA256`. |

**Regenerate vs. download:** regenerate = new bytes from current
settings; download = the original bytes, unchanged.

## Example

```ts
const headers = { 'X-Tenant-ID': tenantId };

// Upload + receive the .epp
const fd = new FormData();
fd.append('file', file);
const r = await fetch('/api/v1/rewizor/upload', { method: 'POST', headers, body: fd });
if (r.status === 412) return router.push('/settings/accounting');
if (!r.ok) throw new Error(await r.text());
const epp = await r.blob();        // save / trigger download
```

## Tenant isolation

Every business-data table carries `tenant_id`; every query filters on
it at the repository layer. Cross-tenant reads return 404, never 403
(no existence leaks).

## Deployment

- `alembic upgrade head` — applies migrations `001`–`005`.
- Required env: `DB_*`, `OPENAI_API_KEY`. Set `REQUIRE_TENANT_HEADER=1`
  in prod. Dev-only: `DEFAULT_TENANT_ID` (falls back to `"default"`).
