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

# Prompt engineered for Polish accounting documents destined for Rewizor GT import.
_REWIZOR_PROMPT = """
Analyze this Polish accounting document image and extract ALL of the
following fields into a single JSON object.  Return ONLY valid JSON —
no markdown fences, no commentary.

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
  "vendor": "seller / supplier company name",
  "customer": "buyer company name",
  "contractor_nip": "seller tax ID / NIP (digits only) or null",
  "contractor_name": "seller full legal name",
  "contractor_street": "seller street address or null",
  "contractor_postal_code": "seller postal code or null",
  "contractor_city": "seller city or null",
  "contractor_region": "seller state / province / województwo or null",
  "contractor_country": "seller country ISO code (PL, US, DE, etc.) or null",
  "customer_nip": "buyer NIP or null",
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
- If the document says "Faktura" and is FROM a supplier -> "FZ"
- If it says "Faktura" and is ISSUED BY the company (sales) -> "FS"
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
  use symbol "00" (reverse charge / odwrotne obciazenie).
- "symbol" for VAT exempt (Polish seller) is "Zw".
  "np" for transactions not subject to VAT (nie podlega).
  For standard rates use the numeric string ("23", "8", "5", "0").
- "contractor_country" must be an ISO 3166-1 alpha-2 code (PL, US, DE, etc.).
  If the seller address clearly indicates a country, extract it.
- Use null for any field you cannot find.
- Amounts must be plain numbers (no currency symbols, no spaces).
- NIP / tax ID must contain only digits (strip dashes, spaces, country prefix).
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
        """
        logger.info("Rewizor OCR: analysing %s", image_path)
        base64_image = self._encode_image(image_path)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _REWIZOR_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            max_tokens=2000,
            temperature=0,
        )

        raw = response.choices[0].message.content
        data = self._parse_json(raw)
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
        for key in ("net_amount", "vat_amount", "gross_amount"):
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

        # NIP – digits only
        nip = out.get("contractor_nip")
        if isinstance(nip, str):
            out["contractor_nip"] = re.sub(r"\D", "", nip)

        customer_nip = out.get("customer_nip")
        if isinstance(customer_nip, str):
            out["customer_nip"] = re.sub(r"\D", "", customer_nip)

        # Country – uppercase ISO code
        country = out.get("contractor_country")
        if isinstance(country, str):
            out["contractor_country"] = country.strip().upper()[:2]

        # Currency – uppercase
        currency = out.get("currency")
        if isinstance(currency, str):
            out["currency"] = currency.strip().upper()

        # Payment method → single-letter code
        method = (out.get("payment_method") or "").lower().strip()
        method_map = {
            "przelew": "P",
            "gotówka": "G",
            "gotowka": "G",
            "karta": "K",
            "kompensata": "O",
        }
        out["payment_method"] = method_map.get(method, "P")

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

    def _encode_image(self, image_path: str) -> str:
        if image_path.lower().endswith(".pdf"):
            image_path = self._pdf_to_image(image_path)
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _pdf_to_image(pdf_path: str) -> str:
        doc = fitz.open(pdf_path)
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        out_path = pdf_path.rsplit(".", 1)[0] + "_rewizor.png"
        img.save(out_path, "PNG")
        doc.close()
        return out_path
