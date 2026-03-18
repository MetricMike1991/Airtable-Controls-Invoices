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

        linked_bank = fields.get("Bank Transactions", [])
        linked_bank_ids = (
            [x if isinstance(x, str) else x.get("id", "") for x in linked_bank]
            if isinstance(linked_bank, list) else []
        )

        invoices.append({
            "id": r["id"],
            "business_name": str(fields.get("Business Name", "")),
            "invoice_date": str(fields.get("Date Of Invoice", "")),
            "total_inc_vat": total,
            "total_display": str(total_raw),
            "invoice_number": str(fields.get("Invoice Number", "")),
            "file_name": str(fields.get("File Name", "")),
            "linked_bank_txn_ids": linked_bank_ids,
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


def _parse_date_flexible(date_str: str):
    """Try to parse a date string in various common formats. Returns datetime.date or None."""
    from datetime import datetime as _dt
    date_str = date_str.strip()
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"):
        try:
            return _dt.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def find_proposed_matches(
    progress_callback=None,
) -> dict:
    """
    Find proposed matches between invoices and bank transactions.

    Matching strategy:
      1. Only considers Debit bank transactions
      2. Skips bank txns that already have a Matched Invoice
      3. Skips invoices that already have a linked Bank Transaction
      4. Amount must be within 1% or €1
      5. Date must be within ±14 days (hard cutoff)
      6. Scoring: 40% amount, 35% date proximity, 25% name similarity
      7. One-to-one: greedy best-score-first, each invoice/txn used only once

    Returns dict:
      proposals: list of {txn: dict, invoice: dict, score: float, date_diff: int|None}
      already_matched_txns: int
      already_matched_invs: int
      skipped_credits: int
      skipped_no_match: int
      total_txns: int
      total_invoices: int
    """
    import re

    if progress_callback:
        progress_callback(0, 0, "Fetching invoices from Airtable...")

    invoices = fetch_all_invoices()

    if progress_callback:
        progress_callback(0, 0, "Fetching bank transactions from Airtable...")

    bank_txns = fetch_all_bank_transactions()

    total_txns = len(bank_txns)
    total_invoices = len(invoices)

    if progress_callback:
        progress_callback(0, total_txns, f"Analysing {total_txns} transactions vs {total_invoices} invoices...")

    # --- Classify ---
    already_matched_txns = 0
    already_matched_invs = 0
    skipped_credits = 0

    # Available (unmatched) pools
    avail_txns: list[dict] = []
    for txn in bank_txns:
        if txn.get("matched_invoice_ids"):
            already_matched_txns += 1
        elif txn.get("type", "Debit") != "Debit":
            skipped_credits += 1
        else:
            avail_txns.append(txn)

    avail_invs: dict[str, dict] = {}  # id -> inv
    for inv in invoices:
        if inv.get("linked_bank_txn_ids"):
            already_matched_invs += 1
        else:
            avail_invs[inv["id"]] = inv

    # --- Helpers ---
    MAX_DATE_DIFF = 14  # days

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

    # --- Build all candidate pairs ---
    candidates: list[dict] = []

    for idx, txn in enumerate(avail_txns):
        txn_amount = txn["amount"]
        txn_desc = txn["description"]
        txn_date = _parse_date_flexible(txn["date"])

        for inv_id, inv in avail_invs.items():
            inv_total = float(inv.get("total_inc_vat", 0) or 0)
            if inv_total <= 0:
                continue

            # Amount gate: within 1% or €1
            amount_diff = abs(txn_amount - inv_total)
            if amount_diff > max(inv_total * 0.01, 1.0):
                continue

            inv_date = _parse_date_flexible(inv["invoice_date"])

            # Date gate: ±14 days (if both dates exist)
            date_diff = None
            if txn_date and inv_date:
                date_diff = abs((txn_date - inv_date).days)
                if date_diff > MAX_DATE_DIFF:
                    continue

            # --- Scoring ---
            # Amount score (0-1): 1.0 = exact, drops off within tolerance
            amount_score = max(0, 1.0 - (amount_diff / max(inv_total * 0.01, 1.0)))

            # Date score (0-1): 1.0 = same day, 0.0 = 14 days apart
            if date_diff is not None:
                date_score = max(0, 1.0 - (date_diff / MAX_DATE_DIFF))
            else:
                date_score = 0.3  # partial credit when date unavailable

            # Name score (0-1)
            name_score = _word_score(txn_desc, str(inv.get("business_name", "")))

            overall = 0.40 * amount_score + 0.35 * date_score + 0.25 * name_score

            # Bonus for exact penny match
            if amount_diff < 0.01:
                overall = min(1.0, overall + 0.15)

            if overall >= 0.35:
                candidates.append({
                    "txn": txn,
                    "invoice": inv,
                    "score": round(overall, 4),
                    "date_diff": date_diff,
                    "amount_diff": round(amount_diff, 2),
                })

        if progress_callback:
            progress_callback(idx + 1, len(avail_txns), f"Scoring {idx+1}/{len(avail_txns)} transactions...")

    # --- Greedy one-to-one matching (best score first) ---
    candidates.sort(key=lambda c: c["score"], reverse=True)

    used_txn_ids: set[str] = set()
    used_inv_ids: set[str] = set()
    proposals: list[dict] = []

    for c in candidates:
        txn_id = c["txn"]["airtable_id"]
        inv_id = c["invoice"]["id"]
        if txn_id in used_txn_ids or inv_id in used_inv_ids:
            continue
        used_txn_ids.add(txn_id)
        used_inv_ids.add(inv_id)
        proposals.append(c)

    skipped_no_match = len(avail_txns) - len(proposals)

    if progress_callback:
        progress_callback(
            len(avail_txns), len(avail_txns),
            f"Found {len(proposals)} proposed matches."
        )

    return {
        "proposals": proposals,
        "already_matched_txns": already_matched_txns,
        "already_matched_invs": already_matched_invs,
        "skipped_credits": skipped_credits,
        "skipped_no_match": skipped_no_match,
        "total_txns": total_txns,
        "total_invoices": total_invoices,
    }


def commit_matches(
    proposals: list[dict],
    progress_callback=None,
) -> dict:
    """
    Write approved proposed matches to Airtable.

    Each proposal dict must have: txn.airtable_id and invoice.id.
    Sets 'Matched Invoice' on bank txn and 'Bank Transactions' on invoice.

    Returns dict: {committed: int, errors: int}
    """
    bank_table = _get_bank_txn_table()
    invoice_table = _get_table()

    total = len(proposals)
    committed = 0
    errors = 0

    # Build batch updates
    bank_updates: list[dict] = []
    invoice_updates: dict[str, list[str]] = {}  # inv_id -> [txn_ids]

    for p in proposals:
        txn_id = p["txn"]["airtable_id"]
        inv_id = p["invoice"]["id"]

        bank_updates.append({
            "id": txn_id,
            "fields": {"Matched Invoice": [inv_id]},
        })

        if inv_id not in invoice_updates:
            invoice_updates[inv_id] = []
        invoice_updates[inv_id].append(txn_id)

    # Flush bank updates in batches of 10
    for i in range(0, len(bank_updates), 10):
        batch = bank_updates[i:i+10]
        try:
            bank_table.batch_update(batch, typecast=True)
            committed += len(batch)
        except Exception as e:
            print(f"[AIRTABLE] Batch update error: {e}")
            errors += len(batch)

        if progress_callback:
            done = min(i + 10, len(bank_updates))
            progress_callback(done, total, f"Writing bank transaction links... {done}/{total}")

    # Flush invoice side links in batches of 10
    inv_batch: list[dict] = []
    for inv_id, txn_ids in invoice_updates.items():
        inv_batch.append({
            "id": inv_id,
            "fields": {"Bank Transactions": txn_ids},
        })

    for i in range(0, len(inv_batch), 10):
        batch = inv_batch[i:i+10]
        try:
            invoice_table.batch_update(batch, typecast=True)
        except Exception as e:
            print(f"[AIRTABLE] Invoice link update error: {e}")
            errors += len(batch)

        if progress_callback:
            progress_callback(total, total, f"Writing invoice links...")

    return {"committed": committed, "errors": errors}
