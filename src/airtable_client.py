"""
airtable_client.py – Push extracted invoice data + original file to Airtable.

Uses the pyairtable library.
Expects these env vars:
  AIRTABLE_API_KEY   – Personal Access Token (pat...)
  AIRTABLE_BASE_ID   – The Base ID (appXXXXXXX)
  AIRTABLE_TABLE_NAME – Table ID or name (tblXXXXXXX or "Invoices")

Expected Airtable table columns:
  • Business Name              (Single line text)
  • Date Of Invoice            (Single line text – DD/MM/YYYY)
  • Total Invoice Including VAT (Single line text or Number)
  • Invoice Number             (Single line text)
  • File Name                  (Single line text)
  • Invoice Attachement        (Attachment)
  • Manually Reviewed          (Checkbox)
  • Additional Notes           (Long text)
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from pyairtable import Api

from src.extractor import InvoiceData

load_dotenv()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config() -> tuple[str, str, str]:
    api_key = os.getenv("AIRTABLE_API_KEY", "")
    base_id = os.getenv("AIRTABLE_BASE_ID", "")
    table_name = os.getenv("AIRTABLE_TABLE_NAME", "Invoices")
    if not api_key:
        raise ValueError("AIRTABLE_API_KEY not set in .env")
    if not base_id:
        raise ValueError("AIRTABLE_BASE_ID not set in .env")
    return api_key, base_id, table_name


_cached_table = None


def _get_table():
    global _cached_table
    if _cached_table is None:
        api_key, base_id, table_name = _get_config()
        api = Api(api_key)
        _cached_table = api.table(base_id, table_name)
    return _cached_table


def reset_table_cache():
    """Clear the cached table reference (e.g. after config change)."""
    global _cached_table
    _cached_table = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_invoice(
    invoice_data: InvoiceData,
    filepath: str | Path,
    notes: str = "",
    reviewed: bool = False,
) -> dict:
    """
    Create a record in Airtable with the extracted invoice data.
    Attaches the original file.

    Returns the Airtable record dict on success.
    Raises on failure.
    """
    table = _get_table()
    filename = Path(filepath).name

    # Build the record fields
    fields: dict = {
        "Business Name": invoice_data.business_name,
        "File Name": filename,
    }

    if invoice_data.invoice_date:
        fields["Date Of Invoice"] = invoice_data.invoice_date.strip()

    if invoice_data.total_inc_vat:
        fields["Total Invoice Including VAT"] = invoice_data.total_inc_vat.strip()

    if invoice_data.invoice_number:
        fields["Invoice Number"] = invoice_data.invoice_number.strip()

    # Reviewed checkbox & notes
    fields["Manually Reviewed"] = reviewed
    if notes:
        fields["Additional Notes"] = notes.strip()

    # Read file for attachment
    mime_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
    with open(str(filepath), "rb") as f:
        file_content = f.read()

    # Create the record (typecast=True lets Airtable auto-create/convert fields)
    record = table.create(fields, typecast=True)
    record_id = record["id"]

    # Attach the original file (column: "Invoice Attachement")
    try:
        table.upload_attachment(
            record_id, "Invoice Attachement", filename, file_content, content_type=mime_type
        )
    except (AttributeError, Exception):
        # Don't fail the whole upload if attachment fails
        pass

    return record


def test_connection() -> tuple[bool, str]:
    """
    Test the Airtable connection.
    Returns (success: bool, message: str).
    """
    try:
        table = _get_table()
        records = table.all(max_records=1)
        return True, f"Connected! Table has {len(records)}+ record(s)."
    except ValueError as e:
        return False, f"Config error: {e}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def fetch_all_invoices() -> list[dict]:
    """
    Fetch all invoices from Airtable.
    Returns list of dicts with: id, business_name, invoice_date, total_inc_vat, invoice_number, file_name.
    """
    table = _get_table()
    records = table.all()

    invoices = []
    for r in records:
        fields = r.get("fields", {})
        total_raw = fields.get("Total Invoice Including VAT", "")
        try:
            total = float(
                str(total_raw)
                .replace(",", "")
                .replace("€", "")
                .replace("£", "")
                .replace("$", "")
                .strip()
            )
        except (ValueError, TypeError):
            total = 0.0

        invoices.append({
            "id": r["id"],
            "business_name": str(fields.get("Business Name", "")),
            "invoice_date": str(fields.get("Date Of Invoice", "")),
            "total_inc_vat": total,
            "total_display": str(total_raw),
            "invoice_number": str(fields.get("Invoice Number", "")),
            "file_name": str(fields.get("File Name", "")),
        })

    return invoices
