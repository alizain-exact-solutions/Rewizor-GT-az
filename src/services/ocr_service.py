"""
Rewizor-specialised OCR service.

Uses OpenAI Vision API (gpt-4o) to extract the **full** set of data
required for Rewizor GT EDI++ export:

  - Standard invoice fields (number, dates, amounts)
  - Per-rate VAT breakdown (net / vat / gross per rate)
  - Contractor NIP, address, and identification
  - Payment terms (method, due date)
"""

import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict

import fitz  # PyMuPDF
from openai import OpenAI
from PIL import Image

from src.core.utils import normalize_amount, normalize_date

logger = logging.getLogger(__name__)


class OCRExtractionError(Exception):
    """Raised when OCR extraction or parsing fails."""


# EU member-state prefixes recognised for preservation of foreign VAT format.
_EU_VAT_PREFIXES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}


# Postal-code shapes seen on invoices:
#   Polish:   NN-NNN         (e.g. "05-816")
#   Dutch:    NNNN AA  or NNNNAA  (e.g. "1014 BA", "1014BA")
#   German:   NNNNN          (e.g. "10115")
#   US:       NNNNN[-NNNN]   (e.g. "98109", "94080-1234")
#   UK:       AAN NAA / AANN NAA etc. (variable — use a broad pattern)
_POSTAL_PATTERNS = (
    re.compile(r"\b\d{2}-\d{3}\b"),                        # PL
    re.compile(r"\b\d{4}\s?[A-Z]{2}\b"),                   # NL
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),                   # DE / US
    re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b"),  # UK (broad)
)


def _split_postal_from_street(street: str) -> tuple[str, str]:
    """Extract a postal code embedded in a street string.

    Returns ``(cleaned_street, postal_code)``. Postal is empty when no code
    could be identified. The street is returned trimmed of trailing commas
    and whitespace introduced by the split.
    """
    if not street:
        return street, ""
    text = street.strip()
    for pattern in _POSTAL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        postal = match.group(0).strip()
        # Remove the matched postal plus any adjacent comma/whitespace.
        cleaned = (text[:match.start()] + text[match.end():]).strip(" ,;")
        # Collapse doubled separators left behind by the split.
        cleaned = re.sub(r"\s*,\s*,\s*", ", ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
        return cleaned, postal
    return text, ""


def _normalise_nip(value: Any) -> Any:
    """Normalise a NIP / tax identifier.

    - Polish NIP ("PL1234567890" or "1234567890" or "123-456-78-90")
      → 10 digits only.
    - Foreign EU VAT number ("NL862287339B01", "DE123456789")
      → keep the verbatim uppercased format (prefix + alphanumerics).
    - Non-EU tax IDs (US EIN etc.) → return cleaned uppercase alphanumerics.
    - Null / non-string → unchanged.
    """
    if not isinstance(value, str):
        return value
    raw = value.strip().upper()
    if not raw:
        return ""

    # Strip common separators
    compact = re.sub(r"[\s\-.]", "", raw)

    # Polish NIP: "PL" prefix on an otherwise 10-digit number → drop prefix.
    if compact.startswith("PL") and compact[2:].isdigit() and len(compact[2:]) == 10:
        return compact[2:]

    # Pure digits: assume Polish NIP (truncate to 10 if longer digit runs).
    if compact.isdigit():
        return compact

    # Foreign EU VAT: starts with a known EU prefix → keep full alphanumerics.
    if len(compact) >= 2 and compact[:2] in _EU_VAT_PREFIXES:
        return compact

    # Unknown format (US EIN, GB VAT with "GB", etc.) → keep alphanumerics.
    return compact


# Prompt engineered for Polish accounting documents destined for Rewizor GT import.
_REWIZOR_PROMPT = """
Analyze this accounting document image and extract ALL of the
following fields into a single JSON object.  Return ONLY valid JSON —
no markdown fences, no commentary.

CRITICAL — SELLER vs BUYER IDENTIFICATION:
Every invoice has two parties:
  • SELLER (sprzedawca / dostawca / wystawca / "From" / "Bill From"):
    The company that ISSUED the invoice — the one providing goods or services.
    Their logo usually appears at the top. Labels: "Seller", "Vendor",
    "Sprzedawca", "Wystawca", "From", "Bill From", "Issued by".
  • BUYER (nabywca / odbiorca / "To" / "Bill To" / "Ship To"):
    The company RECEIVING the invoice — the one paying.
    Labels: "Buyer", "Customer", "Nabywca", "Odbiorca", "Bill To", "Ship To".

ALL "contractor_*" fields below refer to the SELLER, NEVER the buyer.
The buyer's details go ONLY into "customer" and "customer_nip".
Do NOT confuse the two — if the buyer has a VAT number (e.g. GB123456789),
that goes into "customer_nip", NOT "contractor_nip".

{
  "doc_type": "one of: FZ, FS, KZ, KS, FZK, FSK, KZK, KSK, WB, RK, PK, DE",
  "invoice_number": "full original document number",
  "issue_date": "YYYY-MM-DD",
  "sale_date": "YYYY-MM-DD or null if same as issue_date",
  "receipt_date": "YYYY-MM-DD or null",
  "payment_due_date": "YYYY-MM-DD or null",
  "payment_method": "przelew | gotówka | karta | kompensata | null",
  "currency": "PLN or other ISO 4217 code (USD, EUR, etc.)",
  "exchange_rate": numeric exchange rate to PLN or null,
  "net_amount": numeric total net,
  "vat_amount": numeric total VAT,
  "gross_amount": numeric total gross (brutto),
  "amount_paid": numeric amount already paid (zapłacono/wpłacono) or 0,
  "vendor": "SELLER company name (the issuer of the invoice)",
  "customer": "BUYER company name (the recipient of the invoice)",
  "contractor_nip": "SELLER's tax ID exactly as printed. If the seller has NO tax ID visible, return null. Polish NIPs: 10 digits. EU VAT: keep 2-letter prefix + suffix (e.g. 'NL862287339B01', 'DE123456789'). IMPORTANT: do NOT put the buyer's VAT number here.",
  "contractor_name": "SELLER's full legal name",
  "contractor_street": "SELLER's STREET AND HOUSE NUMBER ONLY — never include city, postal code, or country",
  "contractor_postal_code": "SELLER's postal code ONLY (e.g. '05-816', '1014BA', '98109'). Extract even when it appears on the same line as the street.",
  "contractor_city": "SELLER's city ONLY (e.g. 'Warszawa', 'Amsterdam', 'Seattle') — never include street or postal code",
  "contractor_region": "SELLER's state / province / województwo or null",
  "contractor_country": "SELLER's country as ISO 3166-1 alpha-2 code (PL, US, DE, NL, ...). Derive from the SELLER's address, not the buyer's. For example: Amazon Web Services, Inc. at 410 Terry Ave North, Seattle, WA → 'US'. Return null only if truly unknown.",
  "customer_nip": "BUYER's tax ID / VAT number or null",
  "transaction_id": "any transaction / payment / reference ID visible on the document (labels: 'Transaction ID', 'Reference', 'Numer transakcji', 'Payment ID', 'Stripe ch_...'). Return the raw value. Null if none.",
  "is_correction": true or false,
  "vat_breakdown": [
    {
      "rate": numeric VAT percentage (e.g. 23, 8, 5, 0),
      "symbol": "23" | "8" | "5" | "0" | "Zw" | "00" | "np",
      "net": numeric net for this rate,
      "vat": numeric VAT for this rate,
      "gross": numeric gross for this rate
    }
  ]
}

Document type classification ("doc_type" field) - choose the BEST match:
  FZ  = Faktura zakupu (purchase invoice - you receive it from a supplier)
  FS  = Faktura sprzedazy (sales invoice - you issue it to a customer)
  KZ  = Koszty zakupu (purchase cost document - transport, fees, etc.)
  KS  = Koszty sprzedazy (selling cost document)
  FZK = Korekta faktury zakupu (purchase invoice correction / credit note received)
  FSK = Korekta faktury sprzedazy (sales invoice correction / credit note issued)
  KZK = Korekta kosztow zakupu (purchase cost correction)
  KSK = Korekta kosztow sprzedazy (selling cost correction)
  WB  = Wyciag bankowy (bank statement)
  RK  = Raport kasowy (cash register report)
  PK  = Polecenie ksiegowania (posting order / journal entry)
  DE  = Dowod wewnetrzny (internal accounting document)

How to pick doc_type:
- IMPORTANT: This system processes INCOMING invoices (invoices received
  from suppliers/vendors). Almost all documents should be "FZ" (purchase
  invoice). Only use "FS" if the document is clearly a sales invoice
  issued BY the uploading company to a customer.
- If the document is an invoice FROM a supplier/vendor → "FZ"
- If the document is an invoice issued BY the company TO a customer → "FS"
- When in doubt, default to "FZ" (purchase invoice).
- Look for keywords: "korekta" (correction), "koszty" (costs),
  "wyciag bankowy" (bank statement), "raport kasowy" (cash report),
  "polecenie ksiegowania" (posting order), "dowod wewnetrzny" (internal).
- If the document has "KOREKTA" in the title -> use the correction variant
  (FZK, FSK, KZK, KSK). Also set "is_correction" to true.
- Look at the document number prefix: FS, FZ, KS, KZ, etc.

Rules:
- For each distinct VAT rate row visible on the document, add one entry
  to "vat_breakdown".  If only one rate, the array has one element.
  For non-VAT documents (WB, RK, PK, DE), set vat_breakdown to [].
- If the invoice is from a FOREIGN (non-Polish) seller and has zero VAT,
  use symbol "np" (nie podlega / not subject to Polish VAT).
  This applies to import usług (import of services) — the buyer must
  self-assess VAT in Poland via reverse charge.
- "symbol" for VAT exempt domestic transactions (Polish seller) is "Zw".
  "np" for transactions not subject to VAT (nie podlega) — including all
  foreign services.
  For standard rates use the numeric string ("23", "8", "5", "0").
- "contractor_country" must be an ISO 3166-1 alpha-2 code (PL, US, DE, etc.).
  Derive it from the SELLER's address. Common examples:
    * Amazon Web Services, Inc. (Seattle, WA) → "US"
    * Google Cloud (Mountain View, CA) → "US"
    * Stripe, Inc. (San Francisco, CA) → "US"
    * Surfshark B.V. (Amsterdam) → "NL"
    * Hetzner Online GmbH (Gunzenhausen) → "DE"
- Use null for any field you cannot find.
- Amounts must be plain numbers (no currency symbols, no spaces).
- NIP / tax ID: For Polish suppliers return 10 digits only (strip dashes,
  spaces, and any leading 'PL'). For foreign suppliers PRESERVE the EU
  VAT format including the 2-letter country prefix and any trailing
  alphanumerics (e.g. 'NL862287339B01', 'DE123456789', 'FR12345678901').
  For non-EU sellers with no EU VAT number (e.g. US companies), return null.
- ADDRESS PARSING: Polish addresses often put the postal code on the same
  line as the city ('05-816 Reguły'); Dutch/EU addresses often put it on
  the same line as the street ('Kabelweg 57, 1014BA' or '1014BA Amsterdam').
  Always split them — "contractor_street" gets ONLY the street + house
  number, "contractor_postal_code" gets ONLY the code, "contractor_city"
  gets ONLY the city name. Never concatenate.
- Payment due date ("payment_due_date"):
  * If the document prints an explicit due date ("Termin płatności",
    "Due date", "Pay by"), use that.
  * If it prints payment terms like "Net 14", "14 days", "7 dni", compute
    issue_date + N days and return as YYYY-MM-DD.
  * Otherwise return null — DO NOT guess issue_date.
- For correction documents, amounts should be as shown on the document
  (typically negative for reductions).
"""


class RewizorOCRService:
    """Extract Rewizor-ready invoice data from a PDF or image."""

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        self.client = OpenAI(api_key=api_key, timeout=120.0, max_retries=3)
        self.model = "gpt-4o"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, image_path: str) -> Dict[str, Any]:
        """Run OCR on *image_path* and return a normalised invoice dict.

        The returned dict is compatible with
        :func:`src.epp.mapper.map_invoice_to_epp`.

        Raises:
            FileNotFoundError: If *image_path* does not exist.
            OCRExtractionError: If the OpenAI API call or JSON parsing fails.
        """
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image/PDF not found: {image_path}")

        logger.info("Rewizor OCR: analysing %s", image_path)

        try:
            base64_images = self._encode_images(image_path)
        except Exception as exc:
            logger.error("Failed to encode image %s: %s", image_path, exc)
            raise OCRExtractionError(f"Image encoding failed: {exc}") from exc

        try:
            content: list[dict] = [{"type": "text", "text": _REWIZOR_PROMPT}]
            for b64_img in base64_images:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64_img}",
                    },
                })

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=2000,
                temperature=0,
            )
        except Exception as exc:
            logger.error("OpenAI API call failed for %s: %s", image_path, exc)
            raise OCRExtractionError(f"OpenAI API call failed: {exc}") from exc

        raw = response.choices[0].message.content
        if not raw:
            raise OCRExtractionError("OpenAI returned empty response")

        try:
            data = self._parse_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse OCR JSON: %s\nRaw: %s", exc, raw[:500])
            raise OCRExtractionError(f"Failed to parse OCR response as JSON: {exc}") from exc

        data = self._normalize(data)
        logger.info("Rewizor OCR: extracted invoice %s", data.get("invoice_number"))
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        """Extract JSON from a GPT response that may contain markdown fences."""
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]
        return json.loads(text.strip())

    @staticmethod
    def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise amounts, dates, NIP, country, and currency."""
        out = dict(data)

        # Amounts
        for key in ("net_amount", "vat_amount", "gross_amount", "amount_paid"):
            out[key] = normalize_amount(out.get(key))

        # Exchange rate (keep as-is float, not absolute value)
        rate = out.get("exchange_rate")
        if rate is not None:
            try:
                out["exchange_rate"] = round(float(rate), 4)
            except (TypeError, ValueError):
                out["exchange_rate"] = None

        # Dates
        for key in ("issue_date", "sale_date", "receipt_date", "payment_due_date"):
            out[key] = normalize_date(out.get(key))

        # Canonical date key expected by the mapper
        out["date"] = out.get("issue_date")

        # NIP normalisation:
        #   - Polish NIPs (10 digits, optional "PL" prefix) → keep 10 digits only.
        #   - Foreign EU VAT numbers (e.g. "NL862287339B01") → keep the full
        #     format including 2-letter prefix and alphanumeric suffix. Field
        #     18 of the Rewizor NAGLOWEK expects the EU VAT number verbatim
        #     for foreign contractors.
        out["contractor_nip"] = _normalise_nip(out.get("contractor_nip"))
        out["customer_nip"] = _normalise_nip(out.get("customer_nip"))

        # Country – uppercase ISO code
        country = out.get("contractor_country")
        if isinstance(country, str):
            out["contractor_country"] = country.strip().upper()[:2]

        # Split an accidentally-concatenated postal code out of the street.
        # OCR sometimes returns "Kabelweg 57, 1014BA" or "Warszawa 00-001"
        # in contractor_street — peel the postal code off into its own field
        # when contractor_postal_code is empty.
        street = out.get("contractor_street")
        postal = out.get("contractor_postal_code")
        if isinstance(street, str) and street and not postal:
            street_clean, extracted_postal = _split_postal_from_street(street)
            if extracted_postal:
                out["contractor_street"] = street_clean
                out["contractor_postal_code"] = extracted_postal

        # Promote the OCR's transaction_id into a stable "notes" string so it
        # lands in NAGLOWEK field 49. Never overwrite an explicit notes value.
        # Clear transaction_id after promotion so the mapper doesn't append it
        # a second time.
        transaction_id = out.get("transaction_id")
        if transaction_id:
            if not out.get("notes"):
                out["notes"] = f"Transaction ID: {str(transaction_id).strip()}"
            out.pop("transaction_id", None)

        # Currency – uppercase
        currency = out.get("currency")
        if isinstance(currency, str):
            out["currency"] = currency.strip().upper()

        # Payment method → canonical Rewizor name ("przelew", "gotówka",
        # "karta", "kompensata"). Rewizor GT v1.12 rejects single-letter
        # codes — the mapper's alias table handles any legacy / English
        # input so we just preserve whatever the OCR produced and let the
        # mapper canonicalise downstream.
        method = (out.get("payment_method") or "").strip()
        out["payment_method"] = method

        # VAT breakdown amounts
        breakdown = out.get("vat_breakdown")
        if isinstance(breakdown, list):
            for row in breakdown:
                for k in ("net", "vat", "gross"):
                    row[k] = normalize_amount(row.get(k))
                r = row.get("rate")
                if r is not None:
                    try:
                        row["rate"] = round(float(r), 2)
                    except (TypeError, ValueError):
                        row["rate"] = 0.0

        # doc_type validation
        from src.epp.constants import VALID_DOC_TYPES, DOC_TYPE_PURCHASE_INVOICE
        raw_type = (out.get("doc_type") or "").strip().upper()
        out["doc_type"] = raw_type if raw_type in VALID_DOC_TYPES else DOC_TYPE_PURCHASE_INVOICE

        # is_correction flag
        out["is_correction"] = bool(out.get("is_correction"))

        return out

    # ------------------------------------------------------------------
    # Image handling (self-contained)
    # ------------------------------------------------------------------

    def _encode_images(self, image_path: str) -> list[str]:
        """Return a list of base64-encoded images (one per page for PDFs)."""
        if image_path.lower().endswith(".pdf"):
            paths = self._pdf_to_images(image_path, max_pages=2)
        else:
            paths = [image_path]
        encoded = []
        for p in paths:
            with open(p, "rb") as f:
                encoded.append(base64.b64encode(f.read()).decode("utf-8"))
        return encoded

    @staticmethod
    def _pdf_to_images(pdf_path: str, max_pages: int = 2) -> list[str]:
        """Render the first *max_pages* pages of a PDF to PNG files."""
        doc = fitz.open(pdf_path)
        pages_to_render = min(len(doc), max_pages)
        out_paths: list[str] = []
        base = pdf_path.rsplit(".", 1)[0]
        for i in range(pages_to_render):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            out_path = f"{base}_rewizor_p{i + 1}.png"
            img.save(out_path, "PNG")
            out_paths.append(out_path)
        doc.close()
        return out_paths
