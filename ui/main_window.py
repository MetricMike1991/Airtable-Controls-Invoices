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

import webbrowser

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

        # Bank statement state
        self._bank_files: list[str] = []
        self._parsed_transactions: dict[str, list[dict]] = {}  # filepath -> transactions
        self._parsed_sources: dict[str, str] = {}  # filepath -> source type
        self._bank_edit_rows: dict[str, list[dict]] = {}  # filepath -> list of row widgets

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

        # Separator
        ctk.CTkFrame(self.sidebar, height=2, fg_color="#333355").pack(fill="x", padx=20, pady=10)

        self.btn_bank = ctk.CTkButton(
            self.sidebar, text="🏦  Bank Statements", width=190, height=40,
            fg_color="transparent", hover_color="#333355",
            command=self._show_bank_tab,
        )
        self.btn_bank.pack(pady=4)

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
        for btn in (self.btn_upload, self.btn_history, self.btn_browse, self.btn_bank):
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
            ctk.CTkButton(
                header_row, text="👁  Open File", width=110, height=30,
                fg_color="#555566", hover_color="#666677",
                font=ctk.CTkFont(size=12),
                command=lambda p=fp: self._open_file(p),
            ).pack(side="right", padx=(0, 10))
            ctk.CTkLabel(
                header_row, text=f"Confidence: {data.confidence.upper()}",
                font=ctk.CTkFont(size=12, weight="bold"), text_color=conf_color,
            ).pack(side="right", padx=(0, 10))

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

            # Additional Notes
            next_row = 4
            ctk.CTkLabel(
                fields_frame, text="Additional Notes",
                font=ctk.CTkFont(size=11), text_color=TEXT_DIM, width=180,
            ).grid(row=next_row, column=0, sticky="nw", pady=3)
            notes_entry = ctk.CTkTextbox(
                fields_frame, width=320, height=70,
                fg_color="#1E1E2E", border_color="#555566",
                font=ctk.CTkFont(size=12),
            )
            notes_entry.grid(row=next_row, column=1, sticky="w", padx=(10, 0), pady=3)
            entries["Additional Notes"] = notes_entry

            # Manually Reviewed & Verified checkbox
            reviewed_var = ctk.BooleanVar(value=False)
            reviewed_cb = ctk.CTkCheckBox(
                fields_frame, text="  Manually Reviewed & Verified",
                variable=reviewed_var,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
                fg_color=SUCCESS, hover_color="#15803D",
                border_color="#555566",
                checkbox_width=22, checkbox_height=22,
            )
            reviewed_cb.grid(row=next_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 4))
            entries["Reviewed"] = reviewed_var

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

            # Read additional fields
            notes_widget = entries.get("Additional Notes")
            notes_text = ""
            if notes_widget and hasattr(notes_widget, "get"):
                notes_text = notes_widget.get("1.0", "end").strip()

            reviewed_var = entries.get("Reviewed")
            reviewed = reviewed_var.get() if reviewed_var else False

            upload_items.append((fp, data, notes_text, reviewed))

        if not upload_items:
            self.btn_upload_all.configure(state="normal", text="☁️  Upload All to Airtable")
            self.lbl_upload_status.configure(text="Nothing to upload (all errored).", text_color=WARNING)
            return

        def _run():
            from src.airtable_client import upload_invoice

            total = len(upload_items)
            uploaded = 0
            failed = 0

            for i, (fp, data, notes, reviewed) in enumerate(upload_items):
                name = Path(fp).name
                self.after(0, lambda n=name, idx=i: self.lbl_upload_status.configure(
                    text=f"Uploading {idx + 1}/{total}: {n}..."
                ))

                try:
                    upload_invoice(data, fp, notes=notes, reviewed=reviewed)
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
    # Tab: Bank Statements
    # ------------------------------------------------------------------

    def _show_bank_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_bank)

        container = ctk.CTkScrollableFrame(self.main_frame, fg_color=BG_DARK)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(
            container, text="Bank Statement Upload",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(
            container, text="Upload BOI or SumUp bank statements → Parse transactions → Review → Upload to Airtable",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM, wraplength=700,
        ).pack(anchor="w", pady=(0, 20))

        # ---- Step 1: File selection ----
        step1 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step1.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step1, text="Step 1 — Select Statement Files",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            step1, text="Supported: PDF (BOI / SumUp), Excel (.xlsx), CSV",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        btn_row = ctk.CTkFrame(step1, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 6))

        ctk.CTkButton(
            btn_row, text="📂  Browse Files", width=160, height=38,
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._bank_browse_files,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row, text="🗑  Clear All", width=120, height=38,
            fg_color="#555566", hover_color="#666677",
            command=self._bank_clear_files,
        ).pack(side="left")

        self.bank_file_list_frame = ctk.CTkFrame(step1, fg_color="transparent")
        self.bank_file_list_frame.pack(fill="x", padx=20, pady=(0, 16))

        self.lbl_bank_file_count = ctk.CTkLabel(
            self.bank_file_list_frame, text="No files selected",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_bank_file_count.pack(anchor="w")

        # ---- Step 2: Parse ----
        step2 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step2.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step2, text="Step 2 — Parse Transactions",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            step2, text="Reads CSV/Excel directly, or uses GPT-4o-mini to extract transactions from PDF statements.",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM, wraplength=700,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        self.btn_bank_parse = ctk.CTkButton(
            step2, text="🤖  Parse Statement Files", width=260, height=40,
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._bank_parse_all,
        )
        self.btn_bank_parse.pack(padx=20, anchor="w", pady=(0, 6))

        self.bank_parse_progress = ctk.CTkProgressBar(step2, width=500, height=8)
        self.bank_parse_progress.pack(padx=20, anchor="w", pady=(0, 4))
        self.bank_parse_progress.set(0)

        self.lbl_bank_parse_status = ctk.CTkLabel(
            step2, text="", font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_bank_parse_status.pack(anchor="w", padx=20, pady=(0, 16))

        # ---- Step 3: Review ----
        step3 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step3.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step3, text="Step 3 — Review & Edit Transactions",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 10))

        self.bank_review_frame = ctk.CTkFrame(step3, fg_color="transparent")
        self.bank_review_frame.pack(fill="x", padx=20, pady=(0, 16))

        self.lbl_bank_no_data = ctk.CTkLabel(
            self.bank_review_frame, text="No parsed data yet. Run parsing first.",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_bank_no_data.pack(anchor="w")

        # ---- Step 4: Upload ----
        step4 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=12)
        step4.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            step4, text="Step 4 — Upload to Airtable",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(16, 10))

        self.btn_bank_upload = ctk.CTkButton(
            step4, text="☁️  Upload All Transactions to Airtable", width=300, height=42,
            fg_color=SUCCESS, hover_color="#15803D",
            command=self._bank_upload_all,
        )
        self.btn_bank_upload.pack(padx=20, anchor="w", pady=(0, 6))

        self.bank_upload_progress = ctk.CTkProgressBar(step4, width=500, height=8)
        self.bank_upload_progress.pack(padx=20, anchor="w", pady=(0, 4))
        self.bank_upload_progress.set(0)

        self.lbl_bank_upload_status = ctk.CTkLabel(
            step4, text="", font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_bank_upload_status.pack(anchor="w", padx=20, pady=(0, 16))

    # ------------------------------------------------------------------
    # Bank Statements: Actions
    # ------------------------------------------------------------------

    def _bank_browse_files(self):
        filepaths = filedialog.askopenfilenames(
            title="Select Bank Statement Files",
            filetypes=[
                ("Statement Files", "*.pdf *.xlsx *.xls *.csv"),
                ("All Files", "*.*"),
            ],
        )
        if filepaths:
            for fp in filepaths:
                ext = Path(fp).suffix.lower()
                if fp not in self._bank_files and ext in {".pdf", ".xlsx", ".xls", ".csv"}:
                    self._bank_files.append(fp)
            self._bank_refresh_file_list()

    def _bank_clear_files(self):
        self._bank_files.clear()
        self._parsed_transactions.clear()
        self._parsed_sources.clear()
        self._bank_edit_rows.clear()
        self._show_bank_tab()

    def _bank_refresh_file_list(self):
        n = len(self._bank_files)
        if n == 0:
            self.lbl_bank_file_count.configure(text="No files selected")
        else:
            names = [Path(f).name for f in self._bank_files]
            display = "\n".join(f"  • {name}" for name in names)
            self.lbl_bank_file_count.configure(text=f"{n} file(s) selected:\n{display}")

    def _bank_parse_all(self):
        if not self._bank_files:
            messagebox.showwarning("No Files", "Please select bank statement files first.")
            return

        self.btn_bank_parse.configure(state="disabled", text="⏳  Parsing...")
        self.bank_parse_progress.set(0)
        self.lbl_bank_parse_status.configure(text="Starting parsing...", text_color=TEXT_DIM)

        def _run():
            from src.statement_parser import parse_statement

            total = len(self._bank_files)
            for i, fp in enumerate(self._bank_files):
                name = Path(fp).name
                self.after(0, lambda n=name, idx=i: self.lbl_bank_parse_status.configure(
                    text=f"Parsing {idx + 1}/{total}: {n}..."
                ))

                try:
                    def _progress_cb(cur, tot, msg):
                        self.after(0, lambda m=msg: self.lbl_bank_parse_status.configure(text=m))

                    txns, source = parse_statement(fp, progress_callback=_progress_cb)
                    self._parsed_transactions[fp] = txns
                    self._parsed_sources[fp] = source
                except Exception as e:
                    self._parsed_transactions[fp] = []
                    self._parsed_sources[fp] = "error"
                    print(f"[PARSE ERROR] {name}: {e}")

                progress = (i + 1) / total
                self.after(0, lambda p=progress: self.bank_parse_progress.set(p))

            self.after(0, self._bank_on_parse_done)

        threading.Thread(target=_run, daemon=True).start()

    def _bank_on_parse_done(self):
        self.btn_bank_parse.configure(state="normal", text="🤖  Parse Statement Files")
        self.bank_parse_progress.set(1.0)

        total_txns = sum(len(t) for t in self._parsed_transactions.values())
        errors = sum(1 for s in self._parsed_sources.values() if s == "error")
        msg = f"Done! {total_txns} transactions found across {len(self._parsed_transactions)} file(s)"
        if errors:
            msg += f" ({errors} file(s) failed)"
        self.lbl_bank_parse_status.configure(
            text=msg, text_color=SUCCESS if not errors else WARNING,
        )
        self._bank_render_review()

    def _bank_render_review(self):
        for w in self.bank_review_frame.winfo_children():
            w.destroy()

        if not self._parsed_transactions or all(len(t) == 0 for t in self._parsed_transactions.values()):
            ctk.CTkLabel(
                self.bank_review_frame, text="No transactions parsed yet.",
                font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
            ).pack(anchor="w")
            return

        self._bank_edit_rows = {}

        for fp, txns in self._parsed_transactions.items():
            if not txns:
                continue

            name = Path(fp).name
            source = self._parsed_sources.get(fp, "unknown").upper()

            # Summary card
            card = ctk.CTkFrame(self.bank_review_frame, fg_color="#333350", corner_radius=10)
            card.pack(fill="x", pady=8)

            # Header with file name, source, open button
            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=16, pady=(12, 6))

            ctk.CTkLabel(
                header_row, text=f"🏦 {name}",
                font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT,
            ).pack(side="left")

            ctk.CTkButton(
                header_row, text="👁  Open File", width=110, height=30,
                fg_color="#555566", hover_color="#666677",
                font=ctk.CTkFont(size=12),
                command=lambda p=fp: self._open_file(p),
            ).pack(side="right", padx=(0, 10))

            # Stats
            total_debits = sum(t["amount"] for t in txns if t.get("type") == "Debit")
            total_credits = sum(t["amount"] for t in txns if t.get("type") == "Credit")

            stats_row = ctk.CTkFrame(card, fg_color="transparent")
            stats_row.pack(fill="x", padx=16, pady=(0, 6))

            for label, val, color in [
                (f"Source: {source}", None, TEXT_DIM),
                (f"{len(txns)} transactions", None, TEXT),
                (f"Debits: €{total_debits:,.2f}", None, ERROR),
                (f"Credits: €{total_credits:,.2f}", None, SUCCESS),
            ]:
                ctk.CTkLabel(
                    stats_row, text=label,
                    font=ctk.CTkFont(size=12), text_color=color,
                ).pack(side="left", padx=(0, 20))

            # Transaction table header
            table_frame = ctk.CTkFrame(card, fg_color="transparent")
            table_frame.pack(fill="x", padx=16, pady=(4, 4))

            th = ctk.CTkFrame(table_frame, fg_color="#444466", corner_radius=6)
            th.pack(fill="x", pady=(0, 2))
            for col, w in [("", 30), ("Date", 100), ("Description", 250), ("Amount", 90), ("Type", 70)]:
                ctk.CTkLabel(
                    th, text=col, width=w,
                    font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT,
                ).pack(side="left", padx=4, pady=6)

            # Transaction rows (scrollable area for large statements)
            txn_list_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
            txn_list_frame.pack(fill="x")

            edit_rows = []
            for idx, txn in enumerate(txns):
                row_frame = ctk.CTkFrame(txn_list_frame, fg_color=BG_CARD if idx % 2 == 0 else "#2E2E40", corner_radius=4)
                row_frame.pack(fill="x", pady=1)

                # Include checkbox
                include_var = ctk.BooleanVar(value=True)
                ctk.CTkCheckBox(
                    row_frame, text="", variable=include_var,
                    width=30, checkbox_width=18, checkbox_height=18,
                    fg_color=ACCENT, border_color="#555566",
                ).pack(side="left", padx=4, pady=4)

                # Editable date
                date_entry = ctk.CTkEntry(
                    row_frame, width=100, height=28,
                    fg_color="#1E1E2E", border_color="#555566",
                    font=ctk.CTkFont(size=11),
                )
                date_entry.insert(0, str(txn.get("date", "")))
                date_entry.pack(side="left", padx=4, pady=4)

                # Editable description
                desc_entry = ctk.CTkEntry(
                    row_frame, width=250, height=28,
                    fg_color="#1E1E2E", border_color="#555566",
                    font=ctk.CTkFont(size=11),
                )
                desc_entry.insert(0, str(txn.get("description", "")))
                desc_entry.pack(side="left", padx=4, pady=4)

                # Editable amount
                amt_entry = ctk.CTkEntry(
                    row_frame, width=90, height=28,
                    fg_color="#1E1E2E", border_color="#555566",
                    font=ctk.CTkFont(size=11),
                )
                amt_entry.insert(0, f"{txn.get('amount', 0):.2f}")
                amt_entry.pack(side="left", padx=4, pady=4)

                # Type dropdown (editable)
                txn_type = txn.get("type", "Debit")
                type_var = ctk.StringVar(value=txn_type)
                type_menu = ctk.CTkOptionMenu(
                    row_frame, variable=type_var,
                    values=["Debit", "Credit"],
                    width=90, height=28,
                    fg_color=ERROR if txn_type == "Debit" else SUCCESS,
                    button_color="#444466",
                    button_hover_color="#555577",
                    font=ctk.CTkFont(size=11, weight="bold"),
                )
                # Update colour when type changes
                def _on_type_change(val, menu=type_menu):
                    menu.configure(fg_color=ERROR if val == "Debit" else SUCCESS)
                type_var.trace_add("write", lambda *_, v=type_var, m=type_menu: _on_type_change(v.get(), m))
                type_menu.pack(side="left", padx=4, pady=4)

                edit_rows.append({
                    "include": include_var,
                    "date": date_entry,
                    "description": desc_entry,
                    "amount": amt_entry,
                    "type": type_var,
                })

            self._bank_edit_rows[fp] = edit_rows

            # Bottom padding
            ctk.CTkFrame(card, height=8, fg_color="transparent").pack()

    def _bank_upload_all(self):
        if not self._parsed_transactions:
            messagebox.showwarning("No Data", "Please parse bank statements first.")
            return

        # Collect edited transactions per file
        upload_items: list[tuple[str, list[dict], str]] = []  # (filepath, transactions, source)

        for fp, edit_rows in self._bank_edit_rows.items():
            source = self._parsed_sources.get(fp, "pdf")
            if source == "error":
                continue

            txns = []
            for row in edit_rows:
                if not row["include"].get():
                    continue
                try:
                    amount = float(row["amount"].get().replace(",", "").replace("€", "").strip())
                except (ValueError, TypeError):
                    amount = 0.0

                txns.append({
                    "date": row["date"].get().strip(),
                    "description": row["description"].get().strip(),
                    "amount": amount,
                    "type": row["type"].get() if hasattr(row["type"], "get") else row["type"],
                })

            if txns:
                upload_items.append((fp, txns, source))

        if not upload_items:
            messagebox.showwarning("Nothing to Upload", "No transactions selected for upload.")
            return

        self.btn_bank_upload.configure(state="disabled", text="⏳  Uploading...")
        self.bank_upload_progress.set(0)
        self.lbl_bank_upload_status.configure(text="Uploading to Airtable...", text_color=TEXT_DIM)

        def _run():
            from src.airtable_client import upload_bank_transactions, upload_bank_statement_record

            total_files = len(upload_items)
            total_uploaded = 0
            total_failed = 0

            for fi, (fp, txns, source) in enumerate(upload_items):
                name = Path(fp).name
                self.after(0, lambda n=name, idx=fi: self.lbl_bank_upload_status.configure(
                    text=f"Uploading {idx + 1}/{total_files}: {n} ({len(txns)} txns)..."
                ))

                def _upload_progress(cur, tot, msg):
                    if tot > 0:
                        p = (fi + cur / tot) / total_files
                        self.after(0, lambda pp=p: self.bank_upload_progress.set(pp))
                    self.after(0, lambda m=msg: self.lbl_bank_upload_status.configure(text=m))

                try:
                    uploaded, failed = upload_bank_transactions(
                        txns, source, name, progress_callback=_upload_progress,
                    )
                    total_uploaded += uploaded
                    total_failed += failed

                    # Create statement summary record
                    total_debits = sum(t["amount"] for t in txns if t.get("type") == "Debit")
                    total_credits = sum(t["amount"] for t in txns if t.get("type") == "Credit")
                    dates = [t["date"] for t in txns if t.get("date")]
                    period = f"{dates[0]} - {dates[-1]}" if dates else ""

                    try:
                        upload_bank_statement_record(
                            source_file=name,
                            source=source,
                            transaction_count=len(txns),
                            total_debits=total_debits,
                            total_credits=total_credits,
                            statement_period=period,
                            filepath=fp,
                        )
                    except Exception:
                        pass  # Don't fail if summary record fails

                    self._upload_history.append({
                        "file": name,
                        "business": f"Bank Statement ({source.upper()})",
                        "date": period,
                        "total": f"{uploaded} txns",
                        "status": "success" if failed == 0 else "partial",
                        "time": datetime.now().strftime("%H:%M:%S"),
                    })
                except Exception as e:
                    total_failed += len(txns)
                    self._upload_history.append({
                        "file": name,
                        "business": f"Bank Statement ({source.upper()})",
                        "date": "",
                        "total": "0 txns",
                        "status": "failed",
                        "error": str(e),
                        "time": datetime.now().strftime("%H:%M:%S"),
                    })

            self.after(0, lambda: self._bank_on_upload_done(total_uploaded, total_failed))

        threading.Thread(target=_run, daemon=True).start()

    def _bank_on_upload_done(self, uploaded: int, failed: int):
        self.btn_bank_upload.configure(state="normal", text="☁️  Upload All Transactions to Airtable")
        self.bank_upload_progress.set(1.0)

        if failed == 0:
            msg = f"✅ All {uploaded} transaction(s) uploaded successfully!"
            color = SUCCESS
        else:
            msg = f"⚠️ {uploaded} uploaded, {failed} failed"
            color = WARNING

        self.lbl_bank_upload_status.configure(text=msg, text_color=color)

        # Clear parsed data
        self._bank_files.clear()
        self._parsed_transactions.clear()
        self._parsed_sources.clear()
        self._bank_edit_rows.clear()

    # ------------------------------------------------------------------
    # Open file for manual review
    # ------------------------------------------------------------------

    def _open_file(self, filepath: str):
        """Open the invoice file in the default system viewer / browser."""
        try:
            # file:// URL opens in default browser for PDFs/images
            url = Path(filepath).as_uri()
            webbrowser.open(url)
        except Exception:
            # Fallback: use os.startfile on Windows
            try:
                os.startfile(filepath)
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file:\n{e}")

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
