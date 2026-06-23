# Airtable Invoice & Bank Statement Manager

A Python desktop application for managing invoices and bank statements, with AI-powered data extraction and Airtable integration. Built for a small Irish business workflow.

---

## Table of Contents
- [Features](#features)
- [Architecture](#architecture)
- [Setup on a New PC](#setup-on-a-new-pc)
- [Environment Variables (.env)](#environment-variables-env)
- [Airtable Schema](#airtable-schema)
- [File Structure](#file-structure)
- [Source Code Details](#source-code-details)
- [User Workflows](#user-workflows)
- [Known Behaviours & Notes](#known-behaviours--notes)

---

## Features

### Invoice Upload
- Browse and select invoice files (PDF, images, Excel, CSV)
- AI extraction via OpenAI GPT-4o-mini: Business Name, Date, Total (inc VAT), Invoice Number
- Review & edit extracted data before uploading
- "Open File" button to preview the original file
- "Manually Reviewed" checkbox and "Additional Notes" text field
- Uploads to Airtable with file attachment
- **After upload**: file is moved to `C:\Users\35383\OneDrive\Desktop\Invoices\Already Uploaded` and renamed to `Processed - BusinessName - Amount - Date.ext`

### Bank Statement Parsing
- **BOI PDF statements**: Parsed via GPT-4o-mini vision (page-by-page image extraction)
- **SumUp Excel/CSV**: Auto-detected by column headers, parsed directly with pandas
- **SumUp Bank Export**: Columns `Transaction date | Transaction code | Reference | Amount | Available balance` — negative = Debit, positive = Credit, Description taken from Reference column
- **Generic CSV/Excel**: Fallback parser for other formats
- **PDF uploads**: All transactions default to Debit type
- **Excel uploads**: Debit/Credit auto-detected from data, shown in UI with toggle buttons
- Editable fields in review: date, description, amount, Debit/Credit toggle, include checkbox, Additional Notes
- Yellow tooltip with SumUp bank export instructions (step-by-step guide)

### Invoice ↔ Bank Transaction Matching
- Smart matching: amount tolerance (±1% or €1), date proximity (±14 days), name similarity scoring
- One-to-one enforcement (greedy best-match-first)
- Already-linked records automatically skipped
- Review before commit: checkboxes, score %, date difference shown
- **Reject button (✕)**: dismiss a proposed match — it won't appear again during the session
- Writes "Matched Invoice" and "Bank Transactions" link fields to both sides in Airtable

### Browse Airtable
- Fetches and displays all invoices from Airtable
- Shows "Matched" column (✅/❌) indicating if linked to a bank transaction

### Reports
- Select Airtable table (Invoices or Bank Transactions) and view
- Paste shared view URL for clickable links in the report
- Preview records before generating
- Generates styled Excel (.xlsx) with: data rows, clickable Airtable record links, attachment download links, summary totals

### Other
- 🔄 Sync Airtable button (refreshes cached data)
- 🔌 Test Connection button
- Desktop shortcut (`Invoices.lnk`) on OneDrive Desktop

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  app.py (entry point)                │
│          InvoiceUploaderApp().mainloop()              │
├─────────────────────────────────────────────────────┤
│              ui/main_window.py (~2100 lines)         │
│   CustomTkinter GUI — dark theme, sidebar nav        │
│   Tabs: Upload | History | Browse | Bank | Match |   │
│         Reports                                      │
├─────────────────────────────────────────────────────┤
│                  src/ modules                        │
│                                                      │
│  extractor.py      — OpenAI GPT-4o-mini invoice      │
│                      extraction (text + vision)       │
│                                                      │
│  file_handler.py   — File type detection, PDF→images, │
│                      image→bytes, spreadsheet→text    │
│                                                      │
│  statement_parser.py — Bank statement parsing         │
│     • CSV/Excel: BOI, SumUp, SumUp Bank, Generic      │
│     • PDF: GPT-4o-mini vision (page images)           │
│                                                      │
│  airtable_client.py — All Airtable CRUD operations    │
│     • 3 tables: Invoices, Bank Txns, Bank Statements  │
│     • Upload, fetch, match, commit matches            │
│     • Meta API for views and linked records            │
│                                                      │
│  report_generator.py — Excel report generation        │
│     • Styled headers, clickable links, totals         │
└─────────────────────────────────────────────────────┘
```

---

## Setup on a New PC

### Prerequisites
- **Python 3.10+** (tested on 3.13)
- **Git**
- **Windows** (paths are Windows-specific)

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/MetricMike1991/Airtable-Controls-Invoices.git
cd Airtable-Controls-Invoices

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env file (see section below)
# Copy the .env file from the existing PC, or create from .env.example

# 4. Run the app
python app.py
# Or double-click run.bat
```

### Creating a Desktop Shortcut (Windows)
Create a shortcut to `run.bat` on your desktop. Set the working directory to the repo folder.

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\OneDrive\Desktop\Invoices.lnk")
$Shortcut.TargetPath = "C:\Users\35383\Airtable-Controls-Invoices\run.bat"
$Shortcut.WorkingDirectory = "C:\Users\35383\Airtable-Controls-Invoices"
$Shortcut.Save()
```

> **Note**: Update the path if the repo is cloned to a different location.

---

## Environment Variables (.env)

The `.env` file is **not committed to git** (listed in `.gitignore`). You must create it manually or copy from the existing PC.

```env
# OpenAI API Key (for invoice extraction + PDF bank statement parsing)
OPENAI_API_KEY=sk-proj-...

# Airtable Configuration
AIRTABLE_API_KEY=pat...
AIRTABLE_BASE_ID=appy3eTdCr5KKndIs
AIRTABLE_TABLE_NAME=tblyJbZN5kWf2Q01I
AIRTABLE_BANK_TABLE_ID=tbl5Ft9jJxW1IQ65c
AIRTABLE_BANK_STATEMENTS_TABLE_ID=tbl9DK9mbj3UVvONL
```

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o-mini (invoice extraction + PDF parsing) |
| `AIRTABLE_API_KEY` | Airtable personal access token |
| `AIRTABLE_BASE_ID` | Airtable base ID (starts with `app`) |
| `AIRTABLE_TABLE_NAME` | Invoices table ID (starts with `tbl`) |
| `AIRTABLE_BANK_TABLE_ID` | Bank Transactions table ID |
| `AIRTABLE_BANK_STATEMENTS_TABLE_ID` | Bank Statements table ID |

---

## Airtable Schema

### Invoices Table (`tblyJbZN5kWf2Q01I`)

| Column Name | Type | Notes |
|---|---|---|
| Business Name | Single line text | Extracted by AI |
| Date Of Invoice | Single line text | DD/MM/YYYY format |
| Total Invoice Including VAT | Single line text | Numeric string |
| Invoice Number | Single line text | |
| File Name | Single line text | Original filename |
| Invoice Attachement | Attachment | Original file uploaded | 
| Additional Notes | Long text | User-entered notes |
| Manually Reviewed | Checkbox | User confirmation |
| Matched Invoice | Link to Bank Transactions | Set by matching |

### Bank Transactions Table (`tbl5Ft9jJxW1IQ65c`)

| Column Name | Type | Notes |
|---|---|---|
| Date | Single line text | DD/MM/YYYY |
| Description | Single line text | Payee/description |
| Amount | Number | Transaction amount |
| Type | Single line text | "Debit" or "Credit" |
| Source | Single line text | "boi", "sumup", or "pdf" |
| Source File | Single line text | Original filename |
| Additional Notes | Long text | User-entered notes |
| Bank Transactions | Link to Invoices | Set by matching |

### Bank Statements Table (`tbl9DK9mbj3UVvONL`)

| Column Name | Type | Notes |
|---|---|---|
| Statement File | Single line text | Filename |
| Source | Single line text | "boi", "sumup", "pdf" |
| Transaction Count | Number | Count of parsed transactions |
| Upload Date | Single line text | When uploaded |
| Statement Attachment | Attachment | Original file |

---

## File Structure

```
Airtable-Controls-Invoices/
├── app.py                      # Entry point
├── run.bat                     # Windows launcher (cd + python app.py)
├── requirements.txt            # Python dependencies
├── .env                        # API keys (NOT in git)
├── .env.example                # Template for .env
├── .gitignore
├── README.md                   # This file
├── src/
│   ├── __init__.py
│   ├── extractor.py            # OpenAI invoice data extraction
│   ├── file_handler.py         # File type detection, PDF/image/spreadsheet conversion
│   ├── airtable_client.py      # All Airtable API operations (~730 lines)
│   ├── statement_parser.py     # Bank statement parsing (~540 lines)
│   └── report_generator.py     # Excel report generation (~280 lines)
└── ui/
    └── main_window.py          # Full GUI (~2100 lines, CustomTkinter)
```

---

## Source Code Details

### `src/extractor.py`
- **`InvoiceData`** dataclass: `business_name`, `invoice_date`, `total_inc_vat`, `invoice_number`, `confidence`, `raw_response`
- **`extract_invoice(filepath)`**: Sends file to GPT-4o-mini (text or vision mode depending on file type). Returns `InvoiceData`. Retries up to 3 times.

### `src/file_handler.py`
- **`file_type(filepath)`**: Returns `"pdf"`, `"image"`, or `"spreadsheet"`
- **`pdf_to_images(filepath, dpi)`**: Renders PDF pages to PNG byte arrays via PyMuPDF
- **`pdf_extract_text(filepath)`**: Extracts raw text from PDF
- **`prepare_for_extraction(filepath)`**: Returns `(content, mode)` where mode is `"text"` or `"vision"`
- **`SUPPORTED_EXTENSIONS`**: Set of all supported file extensions

### `src/statement_parser.py`
- **CSV/Excel auto-detection** via `_detect_format(df)` → `"boi"`, `"sumup"`, `"sumup_bank"`, or `"generic"`
- **`_parse_boi(df)`**: BOI format — Date, Description, Debit, Credit, Balance columns
- **`_parse_sumup(df)`**: SumUp sales format — Date, Transaction Type, Description, Amount
- **`_parse_sumup_bank(df)`**: SumUp bank export — Transaction date, Transaction code, Reference, Amount, Available balance. Uses exact column name matching (not fuzzy). Description comes from **Reference** column.
- **`_parse_generic(df)`**: Fallback for unknown formats
- **`parse_pdf_statement(filepath)`**: GPT-4o-mini vision parsing. Text extraction first, falls back to image-per-page. Parallel processing with ThreadPoolExecutor (4 workers).
- **`parse_statement(filepath)`**: High-level entry point. Returns `(transactions, source_type)`. PDF transactions are forced to Debit type.

### `src/airtable_client.py`
- **`upload_invoice(data, filepath, notes, reviewed)`**: Creates record with `typecast=True` and file attachment
- **`upload_bank_transactions(txns, source, source_file, notes)`**: Batch upload (10 at a time)
- **`upload_bank_statement_record(filepath, source, txn_count)`**: Summary record with attachment
- **`fetch_all_invoices()`**: Returns all invoice records with linked bank txn IDs
- **`fetch_all_bank_transactions()`**: Returns all bank txn records with matched invoice IDs
- **`find_proposed_matches(progress_callback)`**: Smart matching algorithm:
  - Amount tolerance: ±1% or ±€1 (whichever is larger)
  - Date proximity: ±14 days (scored, closer = better)
  - Name similarity: word overlap scoring
  - Greedy one-to-one assignment (best score first)
  - Skips already-linked records and credit transactions
- **`commit_matches(proposals, progress_callback)`**: Writes link fields to both Invoices and Bank Transactions tables
- **`fetch_views_for_table(table_id)`**: Airtable Meta API — lists views
- **`fetch_records_by_view(table_id, view_name)`**: Fetch records filtered by view
- **`build_record_url(record_id)`**: Constructs Airtable record URL

### `src/report_generator.py`
- **`generate_bank_txn_report(records, ...)`**: Excel with Date, Description, Amount, Type, Source, Matched Invoice, clickable links, attachment URLs, summary totals
- **`generate_invoice_report(records, ...)`**: Excel with Business Name, Invoice #, Date, Total, Matched Bank Txn, links, notes, summary totals
- Styled with openpyxl: header fills, link fonts (blue underline), total row background, €-formatted amounts

### `ui/main_window.py`
- **`InvoiceUploaderApp(ctk.CTk)`** — main window class
- Dark theme: `BG_DARK=#1A1A2E`, `BG_CARD=#25253D`, `ACCENT=#2563EB`, `SUCCESS=#16A34A`, `ERROR=#DC2626`
- Sidebar with 6 tab buttons + Sync Airtable + Test Connection
- **State variables**:
  - `_selected_files`, `_extracted_data` — invoice upload flow
  - `_bank_files`, `_parsed_transactions`, `_parsed_sources` — bank statement flow
  - `_rejected_matches` — set of `(invoice_id, txn_id)` pairs dismissed this session
  - `_active_tab` — tracks which tab is shown for sync behaviour
- **Invoice upload flow**: Select files → Extract (threaded) → Review/Edit (editable fields, Open File button) → Upload to Airtable (threaded, moves file on success)
- **Bank statement flow**: Select files → Parse (threaded, supports progress) → Review/Edit (include checkbox, date/desc/amount fields, Debit/Credit toggle, notes) → Upload (batch)
- **Matching flow**: Find Proposed Matches (threaded, progress bar) → Review proposals (checkbox, score, date diff, ✕ reject button) → Confirm & Write

---

## User Workflows

### Monthly Invoice Processing
1. Save invoices to `C:\Users\35383\OneDrive\Desktop\Invoices\To Be Uploaded`
2. Open the app → **Upload Invoices** tab
3. Browse and select files
4. Click **Extract with AI** — review the extracted data
5. Click **Upload All to Airtable**
6. Files automatically move to `...\Already Uploaded` folder, renamed to `Processed - Business - Amount - Date.ext`

### Monthly Bank Statement Processing
1. **BOI**: Download PDF statement from Bank of Ireland online banking
2. **SumUp**: 
   - Go to https://me.sumup.com/en-ie/business-account
   - Export all transaction data (Account View CSV)
   - Upload CSV to Google Drive → Open as Google Sheets
   - Copy Reference column values into Transaction code column
   - Download as Excel (.xlsx)
3. Open the app → **Bank Statements** tab
4. Browse and select files → **Parse** → Review → **Upload**

### Matching Invoices to Bank Transactions
1. **Match Invoices** tab → **Find Proposed Matches**
2. Review proposals — check/uncheck, click ✕ to reject bad matches
3. **Confirm & Write** to link records in Airtable

### Generating Reports for Accountant
1. **Reports** tab → Select table and view
2. Paste shared Airtable view URL (for clickable links in report)
3. Preview → **Generate Excel Report**

---

## Known Behaviours & Notes

- **File rename on upload**: Uses extracted business name + amount + date. Characters not valid in Windows filenames (`<>:"/\|?*`) are stripped.
- **PDF parsing**: Uses GPT-4o-mini vision mode. BOI statements use an enhanced prompt. All PDF transactions default to Debit type (user can toggle in review).
- **SumUp bank export**: Description is taken from the **Reference** column (not Transaction code). Debit/Credit auto-detected from sign of Amount column.
- **Rejected matches**: Stored in-memory only — cleared when the app restarts.
- **Airtable field "Invoice Attachement"**: Intentional typo matching the existing Airtable schema — do not rename without updating the Airtable table.
- **`typecast=True`**: Used on all Airtable writes so fields are auto-created/converted as needed.
- **Desktop shortcut path**: `C:\Users\35383\OneDrive\Desktop\Invoices.lnk` — update if installing on a different user profile.
- **File move path**: Hardcoded to `C:\Users\35383\OneDrive\Desktop\Invoices\Already Uploaded` — update in `ui/main_window.py` if user profile differs.

---

## Dependencies

```
customtkinter>=5.2.0    # GUI framework (dark themed Tkinter)
openai>=1.30.0          # OpenAI API client
pyairtable>=2.3.0       # Airtable API client
PyMuPDF>=1.24.0         # PDF text extraction + page rendering
pandas>=2.2.0           # CSV/Excel parsing
openpyxl>=3.1.0         # Excel report generation
python-dotenv>=1.0.0    # .env file loading
Pillow>=10.0.0          # Image processing
```
