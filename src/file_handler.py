"""
file_handler.py – Detect file type, convert to a format the AI extractor can consume.

Supported inputs:
  • PDF  → extract text (or render pages to images if scanned)
  • Image (JPG / PNG / TIFF / BMP / WEBP) → pass through
  • Excel (.xlsx / .xls) → read with pandas, return as text table
  • CSV → read with pandas, return as text table
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
from PIL import Image

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp",
    ".xlsx", ".xls", ".csv",
}


def is_supported(filepath: str | Path) -> bool:
    return Path(filepath).suffix.lower() in SUPPORTED_EXTENSIONS


def file_type(filepath: str | Path) -> str:
    """Return one of: 'pdf', 'image', 'spreadsheet', 'unknown'."""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}:
        return "image"
    if ext in {".xlsx", ".xls", ".csv"}:
        return "spreadsheet"
    return "unknown"


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def pdf_to_images(filepath: str | Path, dpi: int = 200) -> list[bytes]:
    """Render each PDF page as a PNG byte-string."""
    doc = fitz.open(str(filepath))
    images: list[bytes] = []
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def pdf_extract_text(filepath: str | Path) -> str:
    """Try to extract embedded text from a PDF."""
    doc = fitz.open(str(filepath))
    text_parts: list[str] = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts).strip()


def image_to_bytes(filepath: str | Path) -> bytes:
    """Read an image file and return PNG bytes."""
    img = Image.open(str(filepath))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def spreadsheet_to_text(filepath: str | Path) -> str:
    """Read an Excel / CSV file and return its content as a text table."""
    ext = Path(filepath).suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(str(filepath))
    else:
        df = pd.read_excel(str(filepath))
    return df.to_string(index=False)


def bytes_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


# ---------------------------------------------------------------------------
# High-level: prepare file for the AI extractor
# ---------------------------------------------------------------------------

def prepare_for_extraction(filepath: str | Path) -> dict:
    """
    Return a dict that the extractor can consume.

    For images / scanned PDFs:
        {"mode": "vision", "images_b64": [<base64 PNG>, ...]}

    For text-based PDFs:
        {"mode": "text", "text": "<extracted text>"}

    For spreadsheets:
        {"mode": "text", "text": "<table text>"}
    """
    ft = file_type(filepath)

    if ft == "spreadsheet":
        return {"mode": "text", "text": spreadsheet_to_text(filepath)}

    if ft == "image":
        img_bytes = image_to_bytes(filepath)
        return {"mode": "vision", "images_b64": [bytes_to_base64(img_bytes)]}

    if ft == "pdf":
        text = pdf_extract_text(filepath)
        # If we got meaningful text (> 50 chars), use text mode
        if len(text) > 50:
            return {"mode": "text", "text": text}
        # Otherwise it's a scanned PDF – render to images
        page_images = pdf_to_images(filepath)
        return {
            "mode": "vision",
            "images_b64": [bytes_to_base64(img) for img in page_images],
        }

    raise ValueError(f"Unsupported file type: {Path(filepath).suffix}")
