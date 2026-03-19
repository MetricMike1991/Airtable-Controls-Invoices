"""
statement_parser.py – Parse bank statements from Bank of Ireland and SumUp.

Supports:
  • CSV / Excel – parsed directly with pandas
  • PDF – pages rendered to images or text extracted, then parsed via GPT-4o-mini

Bank of Ireland CSV typically has columns like:
  Date, Description, Debit, Credit, Balance

SumUp CSV/Excel typically has columns like:
  Date, Transaction Type, Description, Amount, Fee, Net, etc.

SumUp Bank Export (Excel) typically has columns like:
  Transaction date, Transaction code, Reference, Amount, Available balance
  (negative Amount = Debit, positive = Credit)
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from src.file_handler import (
    file_type,
    pdf_to_images,
    pdf_extract_text,
    bytes_to_base64,
)

load_dotenv()

# ---------------------------------------------------------------------------
# CSV / Excel parsing
# ---------------------------------------------------------------------------

def _normalise_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower().strip())


def _detect_format(df: pd.DataFrame) -> str:
    cols = {_normalise_col(c) for c in df.columns}
    # SumUp bank export: Transaction date, Transaction code, Reference, Amount, Available balance
    if any("transactioncode" in c for c in cols) and any("availablebalance" in c for c in cols):
        return "sumup_bank"
    if any("transactiontype" in c or "salesamount" in c or "sumup" in c for c in cols):
        return "sumup"
    if any("debit" in c or "credit" in c for c in cols):
        return "boi"
    return "generic"


def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    norm_map = {_normalise_col(c): c for c in df.columns}
    for cand in candidates:
        cand_norm = _normalise_col(cand)
        for col_norm, col_real in norm_map.items():
            if cand_norm in col_norm or col_norm in cand_norm:
                return col_real
    return None


def _parse_amount(val) -> float:
    if pd.isna(val):
        return 0.0
    s = str(val).replace(",", "").replace("€", "").replace("£", "").replace("$", "").strip()
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def _parse_date(val) -> str:
    if pd.isna(val):
        return ""
    s = str(val).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d %b %Y", "%d %B %Y"):
        try:
            from datetime import datetime
            dt = datetime.strptime(s[:10], fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    try:
        dt = pd.to_datetime(s, dayfirst=True)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return s[:10]


def parse_csv_excel(filepath: str | Path) -> list[dict]:
    ext = Path(filepath).suffix.lower()
    if ext == ".csv":
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(str(filepath), encoding=enc)
                break
            except Exception:
                continue
        else:
            df = pd.read_csv(str(filepath))
    else:
        df = pd.read_excel(str(filepath))

    if df.empty:
        return []

    fmt = _detect_format(df)
    if fmt == "boi":
        return _parse_boi(df)
    elif fmt == "sumup_bank":
        return _parse_sumup_bank(df)
    elif fmt == "sumup":
        return _parse_sumup(df)
    else:
        return _parse_generic(df)


def _parse_boi(df: pd.DataFrame) -> list[dict]:
    date_col = _find_col(df, "date", "transaction date", "posted date")
    desc_col = _find_col(df, "description", "details", "narrative", "transaction")
    debit_col = _find_col(df, "debit", "debit amount", "withdrawal")
    credit_col = _find_col(df, "credit", "credit amount", "lodgement")
    ref_col = _find_col(df, "reference", "ref")

    results = []
    for _, row in df.iterrows():
        debit = _parse_amount(row.get(debit_col)) if debit_col else 0.0
        credit = _parse_amount(row.get(credit_col)) if credit_col else 0.0

        if debit > 0:
            txn_type = "Debit"
            amount = debit
        elif credit > 0:
            txn_type = "Credit"
            amount = credit
        else:
            continue

        results.append({
            "date": _parse_date(row.get(date_col)) if date_col else "",
            "description": str(row.get(desc_col, "")).strip() if desc_col else "",
            "amount": amount,
            "type": txn_type,
            "reference": str(row.get(ref_col, "")).strip() if ref_col else "",
        })
    return results


def _parse_sumup(df: pd.DataFrame) -> list[dict]:
    date_col = _find_col(df, "date", "transaction date", "payment date")
    desc_col = _find_col(df, "description", "details", "merchant", "recipient")
    amount_col = _find_col(df, "amount", "total", "sales amount", "net amount")
    type_col = _find_col(df, "transaction type", "type", "category")
    ref_col = _find_col(df, "reference", "transaction id", "ref")

    results = []
    for _, row in df.iterrows():
        amount = _parse_amount(row.get(amount_col)) if amount_col else 0.0
        if amount <= 0:
            continue

        desc = str(row.get(desc_col, "")).strip() if desc_col else ""
        txn_type = "Debit"
        if type_col:
            ttype = str(row.get(type_col, "")).strip().lower()
            if ttype:
                if any(w in ttype for w in ("refund", "credit", "incoming", "payout")):
                    txn_type = "Credit"
                desc = f"{desc} ({ttype})" if desc else ttype

        results.append({
            "date": _parse_date(row.get(date_col)) if date_col else "",
            "description": desc,
            "amount": amount,
            "type": txn_type,
            "reference": str(row.get(ref_col, "")).strip() if ref_col else "",
        })
    return results


def _parse_sumup_bank(df: pd.DataFrame) -> list[dict]:
    """
    Parse SumUp bank export format:
      Transaction date | Transaction code | Reference | Amount | Available balance

    Negative Amount = Debit, Positive Amount = Credit.
    Description is ALWAYS taken from the Reference column.
    """
    # Build exact lookup using normalised column names (strips all non-alphanumeric)
    col_lookup = {}
    for c in df.columns:
        key = _normalise_col(c)
        col_lookup[key] = c

    date_col = col_lookup.get("transactiondate")
    code_col = col_lookup.get("transactioncode")
    ref_col = col_lookup.get("reference")
    amount_col = col_lookup.get("amount")

    results = []
    for _, row in df.iterrows():
        # Get raw signed amount
        raw_val = row.get(amount_col) if amount_col else None
        if pd.isna(raw_val):
            continue
        try:
            signed_amount = float(
                str(raw_val).replace(",", "").replace("\u20ac", "").replace("\xa3", "").replace("$", "").strip()
            )
        except (ValueError, TypeError):
            continue

        if signed_amount == 0:
            continue

        # Negative = Debit, Positive = Credit
        if signed_amount < 0:
            txn_type = "Debit"
        else:
            txn_type = "Credit"
        amount = abs(signed_amount)

        # Description: ALWAYS from Reference column
        raw_ref = row.get(ref_col) if ref_col else None
        if pd.isna(raw_ref) or str(raw_ref).strip() in ("", "nan", "None"):
            desc = ""
        else:
            desc = str(raw_ref).strip()

        # Transaction code goes into the reference field (not description)
        raw_code = row.get(code_col) if code_col else None
        if pd.isna(raw_code) or str(raw_code).strip() in ("", "nan", "None"):
            code = ""
        else:
            code = str(raw_code).strip()

        # Only fall back to code if Reference is truly empty
        if not desc and code:
            desc = code

        results.append({
            "date": _parse_date(row.get(date_col)) if date_col else "",
            "description": desc,
            "amount": amount,
            "type": txn_type,
            "reference": code,
        })
    return results


def _parse_generic(df: pd.DataFrame) -> list[dict]:
    date_col = _find_col(df, "date", "transaction date", "posted")
    desc_col = _find_col(df, "description", "details", "narrative", "name", "merchant")
    amount_col = _find_col(df, "amount", "debit", "total", "value", "sum")
    ref_col = _find_col(df, "reference", "ref")

    results = []
    for _, row in df.iterrows():
        amount = _parse_amount(row.get(amount_col)) if amount_col else 0.0
        if amount <= 0:
            continue
        results.append({
            "date": _parse_date(row.get(date_col)) if date_col else "",
            "description": str(row.get(desc_col, "")).strip() if desc_col else "",
            "amount": amount,
            "type": "Debit",
            "reference": str(row.get(ref_col, "")).strip() if ref_col else "",
        })
    return results


# ---------------------------------------------------------------------------
# PDF parsing (via GPT-4o-mini vision)
# ---------------------------------------------------------------------------

PDF_SYSTEM_PROMPT = """\
You are a bank statement parser. You will be given an image of a bank statement page.
Extract ALL transactions (both debit AND credit) from this page as a JSON array.

Each transaction should have:
- "date": the transaction date in DD/MM/YYYY format
- "description": the payee/description text
- "amount": the amount as a positive number
- "type": either "Debit" (outgoing payment) or "Credit" (incoming payment/lodgement)
- "reference": any reference number (or empty string if none)

Rules:
- Include BOTH outgoing (Debit) and incoming (Credit) transactions
- Do NOT include balance rows, header rows, or summary rows
- Return amounts as plain positive numbers (e.g. 169.80, not "€169.80")
- If no transactions are found on this page, return an empty array []

Return ONLY valid JSON array. No other text.
Example: [{"date": "09/03/2026", "description": "PH Fire Safety", "amount": 169.80, "type": "Debit", "reference": ""}]
"""

PDF_TEXT_PROMPT = """\
You are a bank statement parser. You will be given the raw text extracted from a bank statement PDF.
Extract ALL transactions (both debit AND credit) as a JSON array.

Each transaction should have:
- "date": the transaction date in DD/MM/YYYY format
- "description": the payee/description text
- "amount": the amount as a positive number
- "type": either "Debit" (outgoing payment) or "Credit" (incoming payment/lodgement)
- "reference": any reference number (or empty string if none)

Rules:
- Include BOTH outgoing (Debit) and incoming (Credit) transactions
- Do NOT include balances, headers, or summaries
- Return amounts as plain positive numbers (e.g. 169.80)
- If no transactions are found, return an empty array []

Return ONLY valid JSON array. No other text.
"""

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
        _client = OpenAI(api_key=api_key, timeout=120.0)
    return _client


def parse_pdf_statement(
    filepath: str | Path,
    progress_callback=None,
) -> list[dict]:
    """
    Parse a PDF bank statement using GPT-4o-mini.
    Tries text extraction first, falls back to vision.
    """
    text = pdf_extract_text(filepath)
    if len(text) > 200:
        result = _parse_pdf_text(text, progress_callback)
        if result:
            return result

    # Fall back to vision
    page_images = pdf_to_images(filepath, dpi=150)
    client = _get_client()
    total_pages = len(page_images)

    def _extract_page(page_idx: int, img_bytes: bytes) -> list[dict]:
        img_b64 = bytes_to_base64(img_bytes)
        messages = [
            {"role": "system", "content": PDF_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": f"Page {page_idx + 1} of the bank statement. Extract all transactions."},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{img_b64}",
                    "detail": "low",
                }},
            ]},
        ]
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.0,
                    max_tokens=4000,
                    timeout=60.0,
                )
                raw = response.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1]
                    raw = raw.rsplit("```", 1)[0]
                raw = raw.strip()
                page_txns = json.loads(raw)
                if isinstance(page_txns, list):
                    return page_txns
                return []
            except Exception:
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
        return []

    all_transactions: list[dict] = []
    page_results: dict[int, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_extract_page, i, img): i
            for i, img in enumerate(page_images)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                page_results[idx] = future.result()
            except Exception:
                page_results[idx] = []
            if progress_callback:
                done = len(page_results)
                progress_callback(done, total_pages, f"Parsed page {done}/{total_pages}")

    for i in sorted(page_results):
        all_transactions.extend(page_results[i])

    return all_transactions


def _parse_pdf_text(text: str, progress_callback=None) -> list[dict]:
    client = _get_client()
    if len(text) > 30000:
        text = text[:30000]

    chunk_size = 4000
    if len(text) > chunk_size:
        chunks = []
        lines = text.split("\n")
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) > chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"
        if current_chunk.strip():
            chunks.append(current_chunk)
    else:
        chunks = [text]

    all_txns: list[dict] = []
    total_chunks = len(chunks)
    for ci, chunk in enumerate(chunks):
        txns = _parse_text_chunk(client, chunk)
        all_txns.extend(txns)
        if progress_callback:
            progress_callback(ci + 1, total_chunks, f"Parsed text chunk {ci+1}/{total_chunks}")

    return all_txns


def _parse_text_chunk(client: OpenAI, text: str) -> list[dict]:
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": PDF_TEXT_PROMPT},
                    {"role": "user", "content": f"Bank statement text:\n\n{text}"},
                ],
                temperature=0.0,
                max_tokens=4000,
                timeout=60.0,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            raw = raw.replace("'", '"')
            result = json.loads(raw)
            if isinstance(result, list):
                return result
        except Exception:
            if attempt < 1:
                time.sleep(2)
    return []


# ---------------------------------------------------------------------------
# High-level: parse any statement file
# ---------------------------------------------------------------------------

def parse_statement(
    filepath: str | Path,
    progress_callback=None,
) -> tuple[list[dict], str]:
    """
    Parse a bank statement file (CSV, Excel, or PDF).
    Returns (transactions, source_type).
    source_type is 'boi', 'sumup', 'sumup_bank', or 'pdf'.
    """
    ft = file_type(filepath)

    if ft == "spreadsheet":
        txns = parse_csv_excel(filepath)

        # Detect source by reading the file and checking format
        ext = Path(filepath).suffix.lower()
        if ext == ".csv":
            try:
                df = pd.read_csv(str(filepath), nrows=0)
            except Exception:
                df = pd.DataFrame()
        else:
            try:
                df = pd.read_excel(str(filepath), nrows=0)
            except Exception:
                df = pd.DataFrame()

        detected = _detect_format(df) if not df.empty or len(df.columns) > 0 else "generic"
        if detected == "sumup_bank":
            source = "sumup"
        elif detected == "sumup":
            source = "sumup"
        elif detected == "boi":
            source = "boi"
        else:
            # Fallback: check CSV header text
            if ext == ".csv":
                try:
                    with open(str(filepath), "r", encoding="utf-8", errors="replace") as f:
                        header = f.readline().lower()
                    source = "sumup" if "sumup" in header or "sales" in header else "boi"
                except Exception:
                    source = "boi"
            else:
                source = "boi"

        return txns, source

    elif ft == "pdf":
        txns = parse_pdf_statement(filepath, progress_callback)
        # PDF uploads default ALL transactions to Debit
        for t in txns:
            t["type"] = "Debit"
        return txns, "pdf"

    else:
        raise ValueError(f"Unsupported statement format: {Path(filepath).suffix}")
