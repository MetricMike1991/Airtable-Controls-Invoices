# Airtable Invoice Uploader

A desktop application that lets you upload invoices and automatically populate the Invoices table in your Airtable base using AI-powered data extraction.

## Features

- **File Upload** – Browse and select invoice files (PDF, images, Excel, CSV)
- **AI Extraction** – Uses OpenAI GPT-4o-mini to extract Business Name, Date, Total, Invoice Number
- **Review & Edit** – Review and correct extracted data before uploading
- **Airtable Sync** – Uploads invoice records + original file attachments to Airtable
- **Browse Records** – View all existing invoices in your Airtable base
- **Upload History** – Track all uploads made during the session

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Copy `.env.example` to `.env` and fill in your keys:

```
OPENAI_API_KEY=sk-proj-...
AIRTABLE_API_KEY=pat...
AIRTABLE_BASE_ID=app...
AIRTABLE_TABLE_NAME=tbl...
```

### 3. Airtable Table Schema

Your Airtable Invoices table should have these columns:

| Column Name                  | Type              |
| ---------------------------- | ----------------- |
| Business Name                | Single line text  |
| Date Of Invoice              | Single line text  |
| Total Invoice Including VAT  | Single line text  |
| Invoice Number               | Single line text  |
| File Name                    | Single line text  |
| Invoice Attachement          | Attachment        |

### 4. Run

```bash
python app.py
```

Or double-click `run.bat` on Windows.

## Supported File Types

- PDF (text-based or scanned)
- Images: JPG, PNG, TIFF, BMP, WEBP
- Spreadsheets: XLSX, XLS, CSV
