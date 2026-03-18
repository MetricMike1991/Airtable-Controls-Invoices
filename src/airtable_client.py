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


# ---------------------------------------------------------------------------
# Bank Statements / Transactions
# ---------------------------------------------------------------------------

def _get_bank_txn_table():
    """Get the Bank Transactions table."""
    bank_table_id = os.getenv("AIRTABLE_BANK_TABLE_ID", "")
    if not bank_table_id:
        raise ValueError("AIRTABLE_BANK_TABLE_ID not set in .env")
    api_key = os.getenv("AIRTABLE_API_KEY", "")
    base_id = os.getenv("AIRTABLE_BASE_ID", "")
    api = Api(api_key)
    return api.table(base_id, bank_table_id)


def _get_bank_statements_table():
    """Get the Bank Statements table."""
    table_id = os.getenv("AIRTABLE_BANK_STATEMENTS_TABLE_ID", "")
    if not table_id:
        raise ValueError("AIRTABLE_BANK_STATEMENTS_TABLE_ID not set in .env")
    api_key = os.getenv("AIRTABLE_API_KEY", "")
    base_id = os.getenv("AIRTABLE_BASE_ID", "")
    api = Api(api_key)
    return api.table(base_id, table_id)


def upload_bank_transactions(
    transactions: list[dict],
    source: str,
    source_file: str,
    progress_callback=None,
) -> tuple[int, int]:
    """
    Upload bank transactions to the Airtable 'Bank Transactions' table.

    Args:
        transactions: list of dicts with: date, description, amount, type, reference
        source: 'boi', 'sumup', or 'pdf'
        source_file: Original filename
        progress_callback: Optional callable(current, total, message)

    Returns (uploaded, failed) counts.
    """
    bank_table = _get_bank_txn_table()

    # Map source to proper case for Airtable singleSelect
    source_map = {"boi": "BOI", "sumup": "SumUp", "pdf": "PDF"}
    source_label = source_map.get(source.lower(), "PDF")

    # Detect statement period from min/max dates
    from datetime import datetime as _dt
    dates = []
    for t in transactions:
        d = str(t.get("date", "")).strip()
        if d:
            try:
                dates.append(_dt.strptime(d, "%d/%m/%Y"))
            except ValueError:
                pass
    statement_period = ""
    if dates:
        min_d = min(dates).strftime("%d/%m/%Y")
        max_d = max(dates).strftime("%d/%m/%Y")
        statement_period = f"{min_d} - {max_d}"

    # Upload in batches of 10
    uploaded = 0
    failed = 0
    batch: list[dict] = []
    total = len(transactions)

    for i, t in enumerate(transactions):
        txn_type = str(t.get("type", "Debit")).strip()
        if txn_type not in ("Debit", "Credit"):
            txn_type = "Debit"

        try:
            amount = abs(float(t.get("amount", 0)))
        except (ValueError, TypeError):
            amount = 0.0

        fields = {
            "Date": str(t.get("date", "")).strip(),
            "Description": str(t.get("description", "")).strip(),
            "Amount": amount,
            "Type": txn_type,
            "Source": source_label,
            "Statement Period": statement_period,
            "Source File": source_file,
        }
        batch.append(fields)

        if len(batch) >= 10:
            try:
                bank_table.batch_create(batch, typecast=True)
                uploaded += len(batch)
            except Exception as e:
                print(f"[AIRTABLE] Batch upload error: {e}")
                failed += len(batch)
            batch = []
            if progress_callback:
                progress_callback(min(i + 1, total), total, f"Uploaded {uploaded} transactions...")

    # Upload remaining
    if batch:
        try:
            bank_table.batch_create(batch, typecast=True)
            uploaded += len(batch)
        except Exception as e:
            print(f"[AIRTABLE] Batch upload error: {e}")
            failed += len(batch)

    if progress_callback:
        progress_callback(total, total, f"Done: {uploaded} uploaded, {failed} failed")

    return uploaded, failed


def upload_bank_statement_record(
    source_file: str,
    source: str,
    transaction_count: int,
    total_debits: float,
    total_credits: float,
    statement_period: str,
    filepath: str | Path | None = None,
) -> dict:
    """
    Create a summary record in the Bank Statements table and attach the original file.
    """
    import mimetypes as mt

    table = _get_bank_statements_table()

    source_map = {"boi": "BOI", "sumup": "SumUp", "pdf": "PDF"}
    source_label = source_map.get(source.lower(), "PDF")

    fields = {
        "Name": source_file,
        "Source": source_label,
        "Transaction Count": transaction_count,
        "Total Debits": round(total_debits, 2),
        "Total Credits": round(total_credits, 2),
        "Statement Period": statement_period,
        "Upload Status": "Uploaded",
        "Upload Date": __import__("datetime").datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    record = table.create(fields, typecast=True)

    # Attach original file
    if filepath:
        try:
            mime = mt.guess_type(str(filepath))[0] or "application/octet-stream"
            with open(str(filepath), "rb") as f:
                content = f.read()
            table.upload_attachment(
                record["id"], "Attachments", Path(filepath).name, content, content_type=mime
            )
        except Exception:
            pass

    return record


def fetch_all_bank_transactions() -> list[dict]:
    """Fetch all bank transactions from Airtable."""
    bank_table = _get_bank_txn_table()
    records = bank_table.all()
    result = []
    for r in records:
        f = r.get("fields", {})
        matched_inv = f.get("Matched Invoice", [])
        result.append({
            "airtable_id": r["id"],
            "date": str(f.get("Date", "")),
            "description": str(f.get("Description", "")),
            "amount": float(f.get("Amount", 0) or 0),
            "type": str(f.get("Type", "Debit")),
            "source": str(f.get("Source", "")),
            "source_file": str(f.get("Source File", "")),
            "matched_invoice_ids": [x if isinstance(x, str) else x.get("id", "") for x in matched_inv] if isinstance(matched_inv, list) else [],
        })
    return result


def auto_match_invoices(
    progress_callback=None,
) -> dict:
    """
    Auto-match invoices to bank transactions by amount.

    For each unmatched Debit bank transaction, find an invoice with matching
    'Total Invoice Including VAT'. If an exact amount match is found, link
    them via the 'Matched Invoice' field on the bank transaction and the
    'Bank Transactions' field on the invoice.

    Returns dict: {matched, skipped, already_matched, total, errors}.
    """
    import re

    bank_table = _get_bank_txn_table()
    invoice_table = _get_table()

    if progress_callback:
        progress_callback(0, 0, "Fetching invoices from Airtable...")

    invoices = fetch_all_invoices()
    if not invoices:
        return {"matched": 0, "skipped": 0, "already_matched": 0, "total": 0, "errors": 0}

    if progress_callback:
        progress_callback(0, 0, "Fetching bank transactions from Airtable...")

    bank_txns = fetch_all_bank_transactions()
    total = len(bank_txns)

    if progress_callback:
        progress_callback(0, total, f"Matching {total} transactions against {len(invoices)} invoices...")

    # Helper: normalise name for comparison
    def _norm(name: str) -> str:
        s = re.sub(r"[^a-z0-9\s]", "", name.lower())
        return " ".join(s.split())

    def _word_score(a: str, b: str) -> float:
        wa = set(_norm(a).split())
        wb = set(_norm(b).split())
        if not wa or not wb:
            return 0.0
        na, nb = _norm(a), _norm(b)
        if na in nb or nb in na:
            return 0.9
        inter = wa & wb
        if not inter:
            return 0.0
        return 2 * len(inter) / (len(wa) + len(wb))

    matched = 0
    skipped = 0
    already_matched = 0
    errors = 0

    # Collect updates to batch
    bank_updates: list[dict] = []
    invoice_updates: dict[str, list[str]] = {}  # invoice_id -> list of bank_txn_ids

    for i, txn in enumerate(bank_txns):
        # Skip if already matched
        if txn.get("matched_invoice_ids"):
            already_matched += 1
            if progress_callback:
                progress_callback(i + 1, total, f"#{i+1}/{total} — already matched")
            continue

        # Only match debits
        if txn.get("type", "Debit") != "Debit":
            skipped += 1
            if progress_callback:
                progress_callback(i + 1, total, f"#{i+1}/{total} — credit, skipped")
            continue

        txn_amount = txn["amount"]
        txn_desc = txn["description"]

        # Find best matching invoice by amount + name similarity
        best_inv = None
        best_score = 0.0

        for inv in invoices:
            inv_total = float(inv.get("total_inc_vat", 0) or 0)
            inv_name = str(inv.get("business_name", ""))

            # Amount must be within 1% or €1
            amount_diff = abs(txn_amount - inv_total)
            if inv_total > 0 and amount_diff > max(inv_total * 0.01, 1.0):
                continue

            # Score: exact amount match is top priority, name similarity is bonus
            amount_score = max(0, 1.0 - (amount_diff / max(inv_total, 0.01))) if inv_total > 0 else 0.0
            name_score = _word_score(txn_desc, inv_name)
            overall = 0.7 * amount_score + 0.3 * name_score

            # Strong boost for exact match
            if amount_diff < 0.01:
                overall = min(1.0, overall + 0.3)

            if overall > best_score:
                best_score = overall
                best_inv = inv

        if best_inv and best_score >= 0.50:
            bank_updates.append({
                "id": txn["airtable_id"],
                "fields": {"Matched Invoice": [best_inv["id"]]},
            })

            # Track invoice side link
            if best_inv["id"] not in invoice_updates:
                invoice_updates[best_inv["id"]] = []
            invoice_updates[best_inv["id"]].append(txn["airtable_id"])

            matched += 1
            if progress_callback:
                progress_callback(
                    i + 1, total,
                    f"#{i+1}/{total} — matched: {txn_desc[:25]} → {best_inv['business_name'][:20]} (€{txn_amount:.2f}, {int(best_score*100)}%)"
                )
        else:
            skipped += 1
            if progress_callback:
                progress_callback(i + 1, total, f"#{i+1}/{total} — no match (€{txn_amount:.2f})")

        # Flush bank updates in batches of 10
        if len(bank_updates) >= 10:
            try:
                bank_table.batch_update(bank_updates, typecast=True)
            except Exception as e:
                print(f"[AIRTABLE] Batch update error: {e}")
                errors += len(bank_updates)
                matched -= len(bank_updates)
            bank_updates = []

    # Flush remaining bank updates
    if bank_updates:
        try:
            bank_table.batch_update(bank_updates, typecast=True)
        except Exception as e:
            print(f"[AIRTABLE] Batch update error: {e}")
            errors += len(bank_updates)
            matched -= len(bank_updates)

    # Update invoice side: link bank transactions
    if progress_callback:
        progress_callback(total, total, "Updating invoice links...")

    inv_batch: list[dict] = []
    for inv_id, txn_ids in invoice_updates.items():
        inv_batch.append({
            "id": inv_id,
            "fields": {"Bank Transactions": txn_ids},
        })
        if len(inv_batch) >= 10:
            try:
                invoice_table.batch_update(inv_batch, typecast=True)
            except Exception as e:
                print(f"[AIRTABLE] Invoice link update error: {e}")
                errors += len(inv_batch)
            inv_batch = []

    if inv_batch:
        try:
            invoice_table.batch_update(inv_batch, typecast=True)
        except Exception as e:
            print(f"[AIRTABLE] Invoice link update error: {e}")
            errors += len(inv_batch)

    return {
        "matched": matched,
        "skipped": skipped,
        "already_matched": already_matched,
        "total": total,
        "errors": errors,
    }
