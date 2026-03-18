"""
extractor.py – Use OpenAI GPT-4o-mini to extract invoice fields from files.

Extracts:
  • business_name  – The company / supplier name on the invoice
  • invoice_date   – Date the invoice was issued (DD/MM/YYYY)
  • total_inc_vat  – Total amount including VAT (numeric, e.g. 1234.56)
  • invoice_number – The invoice / reference number
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict

from openai import OpenAI
from dotenv import load_dotenv

from src.file_handler import prepare_for_extraction

load_dotenv()

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class InvoiceData:
    business_name: str = ""
    invoice_date: str = ""
    total_inc_vat: str = ""
    invoice_number: str = ""
    confidence: str = "low"
    raw_response: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an invoice data extraction assistant. You will be given the content of
a business invoice (either as text or as an image). Extract the following fields:

1. business_name – The name of the company/supplier who ISSUED the invoice.
2. invoice_date  – The date the invoice was issued. Return in DD/MM/YYYY format (e.g. "25/03/2025").
3. total_inc_vat – The total amount INCLUDING VAT/tax. Return as a plain number
   with 2 decimal places (e.g. "1234.56"). Use the GRAND TOTAL / TOTAL DUE
   figure, not a subtotal.
4. invoice_number – The invoice number or reference number.
5. confidence – How confident you are that the extraction is correct:
   "high" (all fields clearly visible), "medium" (some guessing),
   "low" (poor quality / mostly guessing).

Return ONLY valid JSON with exactly these keys:
{
  "business_name": "...",
  "invoice_date": "DD/MM/YYYY",
  "total_inc_vat": "1234.56",
  "invoice_number": "...",
  "confidence": "high|medium|low"
}

If a field cannot be found, return an empty string for that field.
Do NOT include any text outside the JSON object.
"""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env file")
        _client = OpenAI(api_key=api_key)
    return _client


def extract_invoice(filepath: str, max_retries: int = 3) -> InvoiceData:
    """
    Extract invoice data from a file using GPT-4o-mini.
    Supports PDF, images, Excel, CSV.
    """
    prepared = prepare_for_extraction(filepath)
    client = _get_client()

    # Build messages
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    if prepared["mode"] == "text":
        messages.append({
            "role": "user",
            "content": (
                "Here is the invoice content as text. Extract the required fields.\n\n"
                f"{prepared['text']}"
            ),
        })
    else:
        # Vision mode – send images
        content_parts: list[dict] = [
            {"type": "text", "text": "Here is the invoice as image(s). Extract the required fields."},
        ]
        for img_b64 in prepared["images_b64"]:
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_b64}",
                    "detail": "high",
                },
            })
        messages.append({"role": "user", "content": content_parts})

    # Call with retries
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.0,
                max_tokens=500,
            )
            raw = response.choices[0].message.content.strip()

            # Parse JSON – strip markdown fences if present
            json_str = raw
            if json_str.startswith("```"):
                json_str = json_str.split("\n", 1)[1]
                json_str = json_str.rsplit("```", 1)[0]
            json_str = json_str.strip()

            data = json.loads(json_str)
            return InvoiceData(
                business_name=str(data.get("business_name", "")),
                invoice_date=str(data.get("invoice_date", "")),
                total_inc_vat=str(data.get("total_inc_vat", "")),
                invoice_number=str(data.get("invoice_number", "")),
                confidence=str(data.get("confidence", "low")),
                raw_response=raw,
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)

    # All retries failed
    return InvoiceData(
        confidence="error",
        raw_response=f"Extraction failed after {max_retries} attempts: {last_error}",
    )
