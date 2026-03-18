"""
main_window.py – Desktop application for uploading invoices to Airtable.

Features:
  • Browse & select invoice files (PDF, images, Excel, CSV)
  • Extract data with OpenAI GPT-4o-mini
  • Review / edit extracted fields before upload
  • Upload record + file attachment to Airtable
  • View upload history & existing Airtable records
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from dotenv import load_dotenv

from src.file_handler import SUPPORTED_EXTENSIONS, is_supported

load_dotenv()

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#2563EB"       # blue-600
SUCCESS = "#16A34A"      # green-600
WARNING = "#F59E0B"      # amber-500
ERROR = "#DC2626"        # red-600
BG_DARK = "#1E1E2E"
BG_CARD = "#2A2A3C"
TEXT = "#F8F8F2"
TEXT_DIM = "#A0A0B0"

# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class InvoiceUploaderApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title("Airtable Invoice Uploader")
        self.geometry("1100x780")
        self.minsize(900, 650)
        self.configure(fg_color=BG_DARK)

        # State
        self._selected_files: list[str] = []
        self._extracted_data: dict[str, object] = {}   # filepath -> InvoiceData
        self._upload_history: list[dict] = []

        # Layout
        self._build_sidebar()
        self._build_main_area()
        self._show_upload_tab()

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, fg_color="#16162A", corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Title / branding
        ctk.CTkLabel(
            self.sidebar, text="📄 Invoice\nUploader",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT,
        ).pack(pady=(30, 5))
        ctk.CTkLabel(
            self.sidebar, text="Airtable + OpenAI",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        ).pack(pady=(0, 30))

        # Nav buttons
        self.btn_upload = ctk.CTkButton(
            self.sidebar, text="⬆  Upload Invoices", width=190, height=40,
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._show_upload_tab,
        )
        self.btn_upload.pack(pady=4)

        self.btn_history = ctk.CTkButton(
            self.sidebar, text="📋  Upload History", width=190, height=40,
            fg_color="transparent", hover_color="#333355",
            command=self._show_history_tab,
        )
        self.btn_history.pack(pady=4)

        self.btn_browse = ctk.CTkButton(
            self.sidebar, text="🔍  Browse Airtable", width=190, height=40,
            fg_color="transparent", hover_color="#333355",
            command=self._show_browse_tab,
        )
        self.btn_browse.pack(pady=4)

        # Connection test at bottom
        self.sidebar_spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_spacer.pack(fill="both", expand=True)

        self.btn_test = ctk.CTkButton(
            self.sidebar, text="🔌  Test Connection", width=190, height=36,
            fg_color="#333355", hover_color="#444466",
            command=self._test_connection,
        )
        self.btn_test.pack(pady=(0, 10))

        self.lbl_status = ctk.CTkLabel(
            self.sidebar, text="Not connected", font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM, wraplength=190,
        )
        self.lbl_status.pack(pady=(0, 20))

    # ------------------------------------------------------------------
    # Main content area
    # ------------------------------------------------------------------

    def _build_main_area(self):
        self.main_frame = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self.main_frame.pack(side="right", fill="both", expand=True)

    def _clear_main(self):
        for w in self.main_frame.winfo_children():
            w.destroy()

    def _set_active_nav(self, active_btn):
        for btn in (self.btn_upload, self.btn_history, self.btn_browse):
            btn.configure(fg_color="transparent" if btn != active_btn else ACCENT)

    # ------------------------------------------------------------------
    # Tab: Upload Invoices
    # ------------------------------------------------------------------

    def _show_upload_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_upload)

        container = ctk.CTkScrollableFrame(self.main_frame, fg_color=BG_DARK)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(
            container, text="Upload Invoices",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(
            container, text="Select files → Extract data with AI → Review → Upload to Airtable",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM,
        ).pack(anchor="w", pady=(0, 20))

        # ---- Step 1: File selection ----
        step1 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step1.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step1, text="Step 1 — Select Invoice Files",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 4))

        exts = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        ctk.CTkLabel(
            step1, text=f"Supported: {exts}",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        btn_row = ctk.CTkFrame(step1, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 6))

        ctk.CTkButton(
            btn_row, text="📂  Browse Files", width=160, height=38,
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._browse_files,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row, text="🗑  Clear All", width=120, height=38,
            fg_color="#555566", hover_color="#666677",
            command=self._clear_files,
        ).pack(side="left")

        self.file_list_frame = ctk.CTkFrame(step1, fg_color="transparent")
        self.file_list_frame.pack(fill="x", padx=20, pady=(0, 16))

        self.lbl_file_count = ctk.CTkLabel(
            self.file_list_frame, text="No files selected",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_file_count.pack(anchor="w")

        # ---- Step 2: Extract ----
        step2 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step2.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step2, text="Step 2 — Extract Invoice Data (AI)",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 4))

        ctk.CTkLabel(
            step2, text="Uses GPT-4o-mini to read the invoice and extract Business Name, Date, Total, Invoice #.",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM, wraplength=700,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        self.btn_extract = ctk.CTkButton(
            step2, text="🤖  Extract Data from Selected Files", width=280, height=40,
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._extract_all,
        )
        self.btn_extract.pack(padx=20, anchor="w", pady=(0, 6))

        self.extract_progress = ctk.CTkProgressBar(step2, width=500, height=8)
        self.extract_progress.pack(padx=20, anchor="w", pady=(0, 4))
        self.extract_progress.set(0)

        self.lbl_extract_status = ctk.CTkLabel(
            step2, text="", font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_extract_status.pack(anchor="w", padx=20, pady=(0, 16))

        # ---- Step 3: Review & Edit ----
        step3 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step3.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step3, text="Step 3 — Review & Edit Extracted Data",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 10))

        self.review_frame = ctk.CTkFrame(step3, fg_color="transparent")
        self.review_frame.pack(fill="x", padx=20, pady=(0, 16))

        self.lbl_no_data = ctk.CTkLabel(
            self.review_frame, text="No extracted data yet. Run extraction first.",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_no_data.pack(anchor="w")

        # ---- Step 4: Upload ----
        step4 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step4.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step4, text="Step 4 — Upload to Airtable",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 10))

        self.btn_upload_all = ctk.CTkButton(
            step4, text="☁️  Upload All to Airtable", width=250, height=42,
            fg_color=SUCCESS, hover_color="#15803D",
            command=self._upload_all,
        )
        self.btn_upload_all.pack(padx=20, anchor="w", pady=(0, 6))

        self.upload_progress = ctk.CTkProgressBar(step4, width=500, height=8)
        self.upload_progress.pack(padx=20, anchor="w", pady=(0, 4))
        self.upload_progress.set(0)

        self.lbl_upload_status = ctk.CTkLabel(
            step4, text="", font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_upload_status.pack(anchor="w", padx=20, pady=(0, 16))

    # ------------------------------------------------------------------
    # Tab: Upload History
    # ------------------------------------------------------------------

    def _show_history_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_history)

        container = ctk.CTkScrollableFrame(self.main_frame, fg_color=BG_DARK)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            container, text="Upload History",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(
            container, text="Invoices uploaded during this session",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM,
        ).pack(anchor="w", pady=(0, 20))

        if not self._upload_history:
            ctk.CTkLabel(
                container, text="No uploads yet this session.",
                font=ctk.CTkFont(size=13), text_color=TEXT_DIM,
            ).pack(anchor="w")
            return

        # Table header
        header = ctk.CTkFrame(container, fg_color="#333355", corner_radius=8)
        header.pack(fill="x", pady=(0, 4))
        for col, w in [("File", 250), ("Business", 180), ("Date", 110), ("Total", 110), ("Status", 100)]:
            ctk.CTkLabel(
                header, text=col, width=w,
                font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
            ).pack(side="left", padx=6, pady=8)

        for entry in reversed(self._upload_history):
            row = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=8)
            row.pack(fill="x", pady=2)
            status_color = SUCCESS if entry["status"] == "success" else ERROR
            for val, w in [
                (entry.get("file", ""), 250),
                (entry.get("business", ""), 180),
                (entry.get("date", ""), 110),
                (entry.get("total", ""), 110),
            ]:
                ctk.CTkLabel(
                    row, text=val[:35], width=w,
                    font=ctk.CTkFont(size=12), text_color=TEXT,
                ).pack(side="left", padx=6, pady=8)
            ctk.CTkLabel(
                row, text=entry["status"].upper(), width=100,
                font=ctk.CTkFont(size=12, weight="bold"), text_color=status_color,
            ).pack(side="left", padx=6, pady=8)

    # ------------------------------------------------------------------
    # Tab: Browse Airtable
    # ------------------------------------------------------------------

    def _show_browse_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_browse)

        container = ctk.CTkScrollableFrame(self.main_frame, fg_color=BG_DARK)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            container, text="Airtable Invoices",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 5))

        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 16))

        ctk.CTkButton(
            btn_row, text="🔄  Refresh", width=140, height=36,
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=lambda: self._load_airtable_invoices(container),
        ).pack(side="left")

        self._browse_container = container
        self._load_airtable_invoices(container)

    def _load_airtable_invoices(self, container):
        # Remove old rows
        for w in container.winfo_children():
            if hasattr(w, "_is_data_row"):
                w.destroy()

        lbl = ctk.CTkLabel(
            container, text="Loading from Airtable...",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM,
        )
        lbl._is_data_row = True
        lbl.pack(anchor="w")
        self.update_idletasks()

        def _fetch():
            try:
                from src.airtable_client import fetch_all_invoices
                invoices = fetch_all_invoices()
                self.after(0, lambda: self._render_invoices(container, invoices, lbl))
            except Exception as e:
                self.after(0, lambda: lbl.configure(text=f"Error: {e}", text_color=ERROR))

        threading.Thread(target=_fetch, daemon=True).start()

    def _render_invoices(self, container, invoices, loading_lbl):
        loading_lbl.destroy()

        if not invoices:
            lbl = ctk.CTkLabel(
                container, text="No invoices found in Airtable.",
                font=ctk.CTkFont(size=13), text_color=TEXT_DIM,
            )
            lbl._is_data_row = True
            lbl.pack(anchor="w")
            return

        # Count label
        count_lbl = ctk.CTkLabel(
            container, text=f"{len(invoices)} invoice(s) found",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM,
        )
        count_lbl._is_data_row = True
        count_lbl.pack(anchor="w", pady=(0, 10))

        # Header
        header = ctk.CTkFrame(container, fg_color="#333355", corner_radius=8)
        header._is_data_row = True
        header.pack(fill="x", pady=(0, 4))
        for col, w in [("Business Name", 220), ("Invoice #", 130), ("Date", 110), ("Total", 120), ("File", 200)]:
            ctk.CTkLabel(
                header, text=col, width=w,
                font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
            ).pack(side="left", padx=6, pady=8)

        for inv in invoices:
            row = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=8)
            row._is_data_row = True
            row.pack(fill="x", pady=2)
            for val, w in [
                (inv.get("business_name", ""), 220),
                (inv.get("invoice_number", ""), 130),
                (inv.get("invoice_date", ""), 110),
                (inv.get("total_display", ""), 120),
                (inv.get("file_name", ""), 200),
            ]:
                ctk.CTkLabel(
                    row, text=str(val)[:40], width=w,
                    font=ctk.CTkFont(size=12), text_color=TEXT,
                ).pack(side="left", padx=6, pady=8)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_files(self):
        exts_str = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        filepaths = filedialog.askopenfilenames(
            title="Select Invoice Files",
            filetypes=[("Invoice Files", exts_str), ("All Files", "*.*")],
        )
        if filepaths:
            for fp in filepaths:
                if fp not in self._selected_files and is_supported(fp):
                    self._selected_files.append(fp)
            self._refresh_file_list()

    def _clear_files(self):
        self._selected_files.clear()
        self._extracted_data.clear()
        self._refresh_file_list()
        # Re-render upload tab to reset review section
        self._show_upload_tab()

    def _refresh_file_list(self):
        # Update the file count label
        n = len(self._selected_files)
        if n == 0:
            self.lbl_file_count.configure(text="No files selected")
        else:
            names = [Path(f).name for f in self._selected_files]
            display = "\n".join(f"  • {name}" for name in names)
            self.lbl_file_count.configure(text=f"{n} file(s) selected:\n{display}")

    def _extract_all(self):
        if not self._selected_files:
            messagebox.showwarning("No Files", "Please select invoice files first.")
            return

        self.btn_extract.configure(state="disabled", text="⏳  Extracting...")
        self.extract_progress.set(0)
        self.lbl_extract_status.configure(text="Starting extraction...", text_color=TEXT_DIM)

        def _run():
            from src.extractor import extract_invoice

            total = len(self._selected_files)
            for i, fp in enumerate(self._selected_files):
                name = Path(fp).name
                self.after(0, lambda n=name, idx=i: self.lbl_extract_status.configure(
                    text=f"Extracting {idx + 1}/{total}: {n}..."
                ))

                try:
                    data = extract_invoice(fp)
                    self._extracted_data[fp] = data
                except Exception as e:
                    from src.extractor import InvoiceData
                    self._extracted_data[fp] = InvoiceData(
                        confidence="error",
                        raw_response=str(e),
                    )

                progress = (i + 1) / total
                self.after(0, lambda p=progress: self.extract_progress.set(p))

            self.after(0, self._on_extraction_done)

        threading.Thread(target=_run, daemon=True).start()

    def _on_extraction_done(self):
        self.btn_extract.configure(state="normal", text="🤖  Extract Data from Selected Files")
        self.extract_progress.set(1.0)

        ok = sum(1 for d in self._extracted_data.values() if d.confidence != "error")
        err = len(self._extracted_data) - ok
        msg = f"Done! {ok} extracted successfully"
        if err:
            msg += f", {err} failed"
        self.lbl_extract_status.configure(text=msg, text_color=SUCCESS if not err else WARNING)

        # Populate review section
        self._render_review()

    def _render_review(self):
        for w in self.review_frame.winfo_children():
            w.destroy()

        if not self._extracted_data:
            ctk.CTkLabel(
                self.review_frame, text="No extracted data yet.",
                font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
            ).pack(anchor="w")
            return

        self._edit_entries: dict[str, dict] = {}

        for fp, data in self._extracted_data.items():
            name = Path(fp).name
            card = ctk.CTkFrame(self.review_frame, fg_color="#333350", corner_radius=10)
            card.pack(fill="x", pady=6)

            # File name header
            conf_color = SUCCESS if data.confidence == "high" else (
                WARNING if data.confidence == "medium" else ERROR
            )
            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=16, pady=(12, 6))
            ctk.CTkLabel(
                header_row, text=f"📄 {name}",
                font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT,
            ).pack(side="left")
            ctk.CTkLabel(
                header_row, text=f"Confidence: {data.confidence.upper()}",
                font=ctk.CTkFont(size=12, weight="bold"), text_color=conf_color,
            ).pack(side="right")

            # Editable fields
            fields_frame = ctk.CTkFrame(card, fg_color="transparent")
            fields_frame.pack(fill="x", padx=16, pady=(0, 12))

            entries = {}
            for row_idx, (label, value) in enumerate([
                ("Business Name", data.business_name),
                ("Invoice Date (DD/MM/YYYY)", data.invoice_date),
                ("Total Inc. VAT", data.total_inc_vat),
                ("Invoice Number", data.invoice_number),
            ]):
                ctk.CTkLabel(
                    fields_frame, text=label,
                    font=ctk.CTkFont(size=11), text_color=TEXT_DIM, width=180,
                ).grid(row=row_idx, column=0, sticky="w", pady=3)
                entry = ctk.CTkEntry(
                    fields_frame, width=320, height=32,
                    fg_color="#1E1E2E", border_color="#555566",
                )
                entry.insert(0, value or "")
                entry.grid(row=row_idx, column=1, sticky="w", padx=(10, 0), pady=3)
                entries[label] = entry

            self._edit_entries[fp] = entries

    def _upload_all(self):
        if not self._extracted_data:
            messagebox.showwarning("No Data", "Please extract invoice data first.")
            return

        self.btn_upload_all.configure(state="disabled", text="⏳  Uploading...")
        self.upload_progress.set(0)
        self.lbl_upload_status.configure(text="Uploading to Airtable...", text_color=TEXT_DIM)

        # Collect current edited values
        upload_items = []
        for fp, data in self._extracted_data.items():
            if data.confidence == "error":
                continue
            # Read edits
            entries = self._edit_entries.get(fp, {})
            if entries:
                data.business_name = entries.get("Business Name", data.business_name)
                if hasattr(data.business_name, "get"):
                    data.business_name = data.business_name.get()
                data.invoice_date = entries.get("Invoice Date (DD/MM/YYYY)", data.invoice_date)
                if hasattr(data.invoice_date, "get"):
                    data.invoice_date = data.invoice_date.get()
                data.total_inc_vat = entries.get("Total Inc. VAT", data.total_inc_vat)
                if hasattr(data.total_inc_vat, "get"):
                    data.total_inc_vat = data.total_inc_vat.get()
                data.invoice_number = entries.get("Invoice Number", data.invoice_number)
                if hasattr(data.invoice_number, "get"):
                    data.invoice_number = data.invoice_number.get()
            upload_items.append((fp, data))

        if not upload_items:
            self.btn_upload_all.configure(state="normal", text="☁️  Upload All to Airtable")
            self.lbl_upload_status.configure(text="Nothing to upload (all errored).", text_color=WARNING)
            return

        def _run():
            from src.airtable_client import upload_invoice

            total = len(upload_items)
            uploaded = 0
            failed = 0

            for i, (fp, data) in enumerate(upload_items):
                name = Path(fp).name
                self.after(0, lambda n=name, idx=i: self.lbl_upload_status.configure(
                    text=f"Uploading {idx + 1}/{total}: {n}..."
                ))

                try:
                    upload_invoice(data, fp)
                    uploaded += 1
                    self._upload_history.append({
                        "file": name,
                        "business": data.business_name,
                        "date": data.invoice_date,
                        "total": data.total_inc_vat,
                        "status": "success",
                        "time": datetime.now().strftime("%H:%M:%S"),
                    })
                except Exception as e:
                    failed += 1
                    self._upload_history.append({
                        "file": name,
                        "business": data.business_name,
                        "date": data.invoice_date,
                        "total": data.total_inc_vat,
                        "status": "failed",
                        "error": str(e),
                        "time": datetime.now().strftime("%H:%M:%S"),
                    })

                progress = (i + 1) / total
                self.after(0, lambda p=progress: self.upload_progress.set(p))

            self.after(0, lambda: self._on_upload_done(uploaded, failed))

        threading.Thread(target=_run, daemon=True).start()

    def _on_upload_done(self, uploaded: int, failed: int):
        self.btn_upload_all.configure(state="normal", text="☁️  Upload All to Airtable")
        self.upload_progress.set(1.0)

        if failed == 0:
            msg = f"✅ All {uploaded} invoice(s) uploaded successfully!"
            color = SUCCESS
        else:
            msg = f"⚠️ {uploaded} uploaded, {failed} failed"
            color = WARNING

        self.lbl_upload_status.configure(text=msg, text_color=color)

        # Clear extracted data so they aren't re-uploaded
        self._selected_files.clear()
        self._extracted_data.clear()

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def _test_connection(self):
        self.lbl_status.configure(text="Testing...", text_color=TEXT_DIM)
        self.btn_test.configure(state="disabled")

        def _run():
            from src.airtable_client import test_connection
            ok, msg = test_connection()
            color = SUCCESS if ok else ERROR
            self.after(0, lambda: self.lbl_status.configure(text=msg, text_color=color))
            self.after(0, lambda: self.btn_test.configure(state="normal"))

        threading.Thread(target=_run, daemon=True).start()
