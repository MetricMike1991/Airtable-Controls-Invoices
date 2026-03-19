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

        # Active tab tracker
        self._active_tab: str = "upload"

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

        self.btn_match = ctk.CTkButton(
            self.sidebar, text="🔗  Match Invoices", width=190, height=40,
            fg_color="transparent", hover_color="#333355",
            command=self._show_match_tab,
        )
        self.btn_match.pack(pady=4)

        self.btn_reports = ctk.CTkButton(
            self.sidebar, text="📊  Reports", width=190, height=40,
            fg_color="transparent", hover_color="#333355",
            command=self._show_reports_tab,
        )
        self.btn_reports.pack(pady=4)

        # Connection test at bottom
        self.sidebar_spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_spacer.pack(fill="both", expand=True)

        self.btn_sync = ctk.CTkButton(
            self.sidebar, text="🔄  Sync Airtable", width=190, height=36,
            fg_color="#1E6F50", hover_color="#16A34A",
            command=self._sync_airtable,
        )
        self.btn_sync.pack(pady=(0, 6))

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
        for btn in (self.btn_upload, self.btn_history, self.btn_browse, self.btn_bank, self.btn_match, self.btn_reports):
            btn.configure(fg_color="transparent" if btn != active_btn else ACCENT)

    # ------------------------------------------------------------------
    # Tab: Upload Invoices
    # ------------------------------------------------------------------

    def _show_upload_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_upload)
        self._active_tab = "upload"

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
        self._active_tab = "history"

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
        self._active_tab = "browse"

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
        for col, w in [("Business Name", 200), ("Invoice #", 110), ("Date", 100), ("Total", 100), ("Matched", 80), ("File", 180)]:
            ctk.CTkLabel(
                header, text=col, width=w,
                font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
            ).pack(side="left", padx=6, pady=8)

        for inv in invoices:
            linked = inv.get("linked_bank_txn_ids", [])
            is_matched = len(linked) > 0
            match_text = f"✅ {len(linked)}" if is_matched else "❌"
            match_color = SUCCESS if is_matched else TEXT_DIM

            row = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=8)
            row._is_data_row = True
            row.pack(fill="x", pady=2)
            for val, w in [
                (inv.get("business_name", ""), 200),
                (inv.get("invoice_number", ""), 110),
                (inv.get("invoice_date", ""), 100),
                (inv.get("total_display", ""), 100),
            ]:
                ctk.CTkLabel(
                    row, text=str(val)[:35], width=w,
                    font=ctk.CTkFont(size=12), text_color=TEXT,
                ).pack(side="left", padx=6, pady=8)

            ctk.CTkLabel(
                row, text=match_text, width=80,
                font=ctk.CTkFont(size=12, weight="bold"), text_color=match_color,
            ).pack(side="left", padx=6, pady=8)

            ctk.CTkLabel(
                row, text=str(inv.get("file_name", ""))[:30], width=180,
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

                    # Move file to "Already Uploaded" folder with processed name
                    try:
                        dest_dir = Path(r"C:\Users\35383\OneDrive\Desktop\Invoices\Already Uploaded")
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        src_path = Path(fp)
                        suffix = src_path.suffix

                        # Build new filename: Processed - Business Name - €Amount - Date
                        biz = (data.business_name or "Unknown").strip()
                        amt = f"€{data.total_inc_vat:,.2f}" if data.total_inc_vat else "€0.00"
                        inv_date = (data.invoice_date or "NoDate").strip()
                        # Sanitise characters not allowed in filenames
                        import re as _re
                        safe = lambda s: _re.sub(r'[<>:"/\\|?*]', '_', s)
                        new_name = f"Processed - {safe(biz)} - {safe(amt)} - {safe(inv_date)}{suffix}"

                        dest_path = dest_dir / new_name
                        # Handle duplicate names
                        if dest_path.exists():
                            counter = 1
                            stem = f"Processed - {safe(biz)} - {safe(amt)} - {safe(inv_date)}"
                            while dest_path.exists():
                                dest_path = dest_dir / f"{stem} ({counter}){suffix}"
                                counter += 1
                        import shutil
                        shutil.move(str(src_path), str(dest_path))
                    except Exception as move_err:
                        print(f"[WARN] Could not move {name}: {move_err}")

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
        self._active_tab = "bank"

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
        ).pack(anchor="w", pady=(0, 12))

        # ---- SumUp Instructions Tooltip ----
        tip_frame = ctk.CTkFrame(container, fg_color="#3B3000", corner_radius=10, border_width=2, border_color="#FACC15")
        tip_frame.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            tip_frame, text="💡  SumUp Bank Export Instructions",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#FACC15",
        ).pack(anchor="w", padx=16, pady=(12, 4))

        tip_text = (
            "1.  Go to  https://me.sumup.com/en-ie/business-account\n"
            "2.  Select the date range and export all transaction data (Account View CSV)\n"
            "3.  Upload CSV to Google Drive → Open as Google Sheets\n"
            "4.  Copy the values from the 'Reference' column into the 'Transaction code' column\n"
            "5.  Download as Excel (.xlsx) and upload here"
        )
        ctk.CTkLabel(
            tip_frame, text=tip_text,
            font=ctk.CTkFont(size=12), text_color="#FDE68A",
            wraplength=650, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))

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
            for col, w in [("", 30), ("Date", 100), ("Description", 250), ("Amount", 90), ("Type", 70), ("Notes", 150)]:
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

                # Type toggle button (click to swap Debit ↔ Credit)
                parsed_type = txn.get("type", "Debit")
                if parsed_type not in ("Debit", "Credit"):
                    parsed_type = "Debit"
                type_var = ctk.StringVar(value=parsed_type)
                _type_fg = ERROR if parsed_type == "Debit" else SUCCESS
                _type_hover = "#B91C1C" if parsed_type == "Debit" else "#15803D"
                type_btn = ctk.CTkButton(
                    row_frame, text=parsed_type, width=90, height=28,
                    fg_color=_type_fg, hover_color=_type_hover,
                    font=ctk.CTkFont(size=11, weight="bold"),
                )

                def _toggle_type(var=type_var, btn=type_btn):
                    if var.get() == "Debit":
                        var.set("Credit")
                        btn.configure(text="Credit", fg_color=SUCCESS, hover_color="#15803D")
                    else:
                        var.set("Debit")
                        btn.configure(text="Debit", fg_color=ERROR, hover_color="#B91C1C")

                type_btn.configure(command=_toggle_type)
                type_btn.pack(side="left", padx=4, pady=4)

                # Additional Notes
                notes_entry = ctk.CTkEntry(
                    row_frame, width=150, height=28,
                    fg_color="#1E1E2E", border_color="#555566",
                    font=ctk.CTkFont(size=11),
                    placeholder_text="Notes...",
                )
                notes_entry.pack(side="left", padx=4, pady=4)

                edit_rows.append({
                    "include": include_var,
                    "date": date_entry,
                    "description": desc_entry,
                    "amount": amt_entry,
                    "type": type_var,
                    "notes": notes_entry,
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
                    "notes": row["notes"].get().strip() if row.get("notes") else "",
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
    # Tab: Match Invoices
    # ------------------------------------------------------------------

    def _show_match_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_match)
        self._active_tab = "match"

        # State for this tab
        self._match_proposals: list[dict] = []
        self._match_checkboxes: list[ctk.BooleanVar] = []

        container = ctk.CTkScrollableFrame(self.main_frame, fg_color=BG_DARK)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            container, text="🔗  Match Invoices to Bank Transactions",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            container,
            text="Smart matching: amount + date proximity (±14 days) + name similarity.\n"
                 "Each invoice and transaction can only match once (one-to-one).\n"
                 "Already-linked records are automatically skipped.",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM, justify="left",
        ).pack(anchor="w", pady=(0, 20))

        # Step 1: Find matches button
        self.btn_find_matches = ctk.CTkButton(
            container, text="🔍  Find Proposed Matches", width=280, height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._find_matches,
        )
        self.btn_find_matches.pack(pady=(0, 15))

        # Progress
        self.match_progress = ctk.CTkProgressBar(container, width=500, height=14)
        self.match_progress.pack(pady=(0, 5))
        self.match_progress.set(0)

        self.lbl_match_status = ctk.CTkLabel(
            container, text="Ready — press Find to analyse records.",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_match_status.pack(pady=(0, 10))

        # Stats area (filled after finding)
        self.match_stats_frame = ctk.CTkFrame(container, fg_color=BG_DARK)
        self.match_stats_frame.pack(fill="x")

        # Action bar (select all / confirm) — hidden until proposals exist
        self.match_action_bar = ctk.CTkFrame(container, fg_color=BG_DARK)
        self.match_action_bar.pack(fill="x", pady=(10, 5))

        # Proposals list
        self.match_proposals_frame = ctk.CTkFrame(container, fg_color=BG_DARK)
        self.match_proposals_frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Step 1: Find proposed matches
    # ------------------------------------------------------------------

    def _find_matches(self):
        self.btn_find_matches.configure(state="disabled", text="⏳  Analysing...")
        self.match_progress.set(0)
        self.lbl_match_status.configure(text="Fetching data from Airtable...", text_color=TEXT_DIM)
        # Clear previous
        for w in self.match_stats_frame.winfo_children():
            w.destroy()
        for w in self.match_action_bar.winfo_children():
            w.destroy()
        for w in self.match_proposals_frame.winfo_children():
            w.destroy()
        self._match_proposals = []
        self._match_checkboxes = []

        def _progress(done, total, msg):
            if total > 0:
                self.after(0, lambda: self.match_progress.set(done / total))
            self.after(0, lambda m=msg: self.lbl_match_status.configure(text=m, text_color=TEXT_DIM))

        def _worker():
            from src.airtable_client import find_proposed_matches
            try:
                result = find_proposed_matches(progress_callback=_progress)
                self.after(0, lambda: self._show_proposals(result))
            except Exception as e:
                self.after(0, lambda: self.lbl_match_status.configure(
                    text=f"❌ Error: {e}", text_color=ERROR
                ))
            finally:
                self.after(0, lambda: self.btn_find_matches.configure(
                    state="normal", text="🔍  Find Proposed Matches"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_proposals(self, result: dict):
        self.match_progress.set(1.0)

        proposals = result.get("proposals", [])
        self._match_proposals = proposals

        already_txns = result.get("already_matched_txns", 0)
        already_invs = result.get("already_matched_invs", 0)
        skipped_credits = result.get("skipped_credits", 0)
        skipped_no_match = result.get("skipped_no_match", 0)
        total_txns = result.get("total_txns", 0)
        total_invs = result.get("total_invoices", 0)

        # Summary status
        if proposals:
            self.lbl_match_status.configure(
                text=f"✅ Found {len(proposals)} proposed match(es). Review below and confirm.",
                text_color=SUCCESS,
            )
        else:
            self.lbl_match_status.configure(
                text="ℹ️ No new matches found.",
                text_color=TEXT_DIM,
            )

        # Stats cards
        frame = self.match_stats_frame
        stats = [
            ("📊 Total Transactions", str(total_txns), TEXT),
            ("📄 Total Invoices", str(total_invs), TEXT),
            ("🔗 Already Matched (txns)", str(already_txns), ACCENT),
            ("🔗 Already Matched (invs)", str(already_invs), ACCENT),
            ("⏭️ Credits Skipped", str(skipped_credits), TEXT_DIM),
            ("❓ No Match Found", str(skipped_no_match), WARNING),
            ("✨ New Matches", str(len(proposals)), SUCCESS),
        ]

        stats_row = ctk.CTkFrame(frame, fg_color=BG_DARK)
        stats_row.pack(fill="x", pady=(0, 10))

        for i, (label, value, clr) in enumerate(stats):
            card = ctk.CTkFrame(stats_row, fg_color=BG_CARD, corner_radius=8, width=140, height=60)
            card.grid(row=i // 4, column=i % 4, padx=4, pady=4, sticky="ew")
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=10), text_color=TEXT_DIM).pack(pady=(6, 0))
            ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=16, weight="bold"), text_color=clr).pack()

        for col in range(4):
            stats_row.grid_columnconfigure(col, weight=1)

        if not proposals:
            return

        # Action bar: Select All + Confirm button
        bar = self.match_action_bar

        self._match_select_all_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            bar, text="Select All", variable=self._match_select_all_var,
            command=self._toggle_select_all_matches,
            font=ctk.CTkFont(size=13), text_color=TEXT,
        ).pack(side="left", padx=(10, 20))

        self.btn_confirm_matches = ctk.CTkButton(
            bar, text=f"✅  Confirm & Write {len(proposals)} Match(es) to Airtable",
            width=360, height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=SUCCESS, hover_color="#15803D",
            command=self._confirm_matches,
        )
        self.btn_confirm_matches.pack(side="right", padx=10)

        # Column headers
        hdr = ctk.CTkFrame(self.match_proposals_frame, fg_color="#333355", corner_radius=6)
        hdr.pack(fill="x", padx=10, pady=(10, 2))

        for col_text, w in [("", 40), ("Bank Transaction", 250), ("Invoice", 250), ("Score", 80), ("Date Δ", 70)]:
            ctk.CTkLabel(
                hdr, text=col_text, font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TEXT_DIM, width=w,
            ).pack(side="left", padx=6, pady=6)

        # Proposal rows
        self._match_checkboxes = []
        for i, prop in enumerate(proposals):
            self._build_proposal_row(i, prop)

    def _build_proposal_row(self, idx: int, prop: dict):
        txn = prop["txn"]
        inv = prop["invoice"]
        score = prop["score"]
        date_diff = prop.get("date_diff")

        row = ctk.CTkFrame(
            self.match_proposals_frame,
            fg_color=BG_CARD, corner_radius=6, height=52,
        )
        row.pack(fill="x", padx=10, pady=2)
        row.pack_propagate(False)

        # Checkbox
        var = ctk.BooleanVar(value=True)
        self._match_checkboxes.append(var)
        ctk.CTkCheckBox(
            row, text="", variable=var, width=30,
            command=self._update_confirm_count,
        ).pack(side="left", padx=(8, 4), pady=8)

        # Bank transaction info
        txn_text = f"{txn['description'][:30]}  •  €{txn['amount']:.2f}  •  {txn['date']}"
        ctk.CTkLabel(
            row, text=txn_text, font=ctk.CTkFont(size=12),
            text_color=TEXT, width=250, anchor="w",
        ).pack(side="left", padx=6)

        # Arrow
        ctk.CTkLabel(row, text="→", font=ctk.CTkFont(size=14), text_color=ACCENT, width=20).pack(side="left")

        # Invoice info
        inv_text = f"{inv['business_name'][:25]}  •  €{inv['total_inc_vat']:.2f}  •  {inv['invoice_date']}"
        ctk.CTkLabel(
            row, text=inv_text, font=ctk.CTkFont(size=12),
            text_color=TEXT, width=250, anchor="w",
        ).pack(side="left", padx=6)

        # Score badge
        score_pct = int(score * 100)
        score_color = SUCCESS if score_pct >= 70 else (WARNING if score_pct >= 50 else ERROR)
        ctk.CTkLabel(
            row, text=f"{score_pct}%",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=score_color, width=60,
        ).pack(side="left", padx=6)

        # Date diff
        dd_text = f"{date_diff}d" if date_diff is not None else "n/a"
        dd_color = SUCCESS if date_diff is not None and date_diff <= 3 else (TEXT_DIM if date_diff is None else WARNING)
        ctk.CTkLabel(
            row, text=dd_text,
            font=ctk.CTkFont(size=12),
            text_color=dd_color, width=50,
        ).pack(side="left", padx=6)

    def _toggle_select_all_matches(self):
        val = self._match_select_all_var.get()
        for var in self._match_checkboxes:
            var.set(val)
        self._update_confirm_count()

    def _update_confirm_count(self):
        count = sum(1 for v in self._match_checkboxes if v.get())
        self.btn_confirm_matches.configure(
            text=f"✅  Confirm & Write {count} Match(es) to Airtable",
            state="normal" if count > 0 else "disabled",
        )

    # ------------------------------------------------------------------
    # Step 2: Confirm and write matches to Airtable
    # ------------------------------------------------------------------

    def _confirm_matches(self):
        selected = [
            self._match_proposals[i]
            for i, var in enumerate(self._match_checkboxes) if var.get()
        ]
        if not selected:
            return

        self.btn_confirm_matches.configure(state="disabled", text="⏳  Writing to Airtable...")
        self.btn_find_matches.configure(state="disabled")
        self.match_progress.set(0)

        def _progress(done, total, msg):
            if total > 0:
                self.after(0, lambda: self.match_progress.set(done / total))
            self.after(0, lambda m=msg: self.lbl_match_status.configure(text=m, text_color=TEXT_DIM))

        def _worker():
            from src.airtable_client import commit_matches
            try:
                result = commit_matches(selected, progress_callback=_progress)
                committed = result.get("committed", 0)
                errs = result.get("errors", 0)
                if errs > 0:
                    msg = f"⚠️ {committed} linked, {errs} errors"
                    clr = WARNING
                else:
                    msg = f"✅ Successfully linked {committed} match(es) in Airtable!"
                    clr = SUCCESS
                self.after(0, lambda: self.lbl_match_status.configure(text=msg, text_color=clr))
                self.after(0, lambda: self.match_progress.set(1.0))
            except Exception as e:
                self.after(0, lambda: self.lbl_match_status.configure(
                    text=f"❌ Error: {e}", text_color=ERROR
                ))
            finally:
                self.after(0, lambda: self.btn_find_matches.configure(state="normal"))
                self.after(0, lambda: self.btn_confirm_matches.configure(
                    state="normal",
                    text=f"✅  Confirm & Write {len(selected)} Match(es) to Airtable",
                ))

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Tab: Reports
    # ------------------------------------------------------------------

    def _show_reports_tab(self):
        self._clear_main()
        self._set_active_nav(self.btn_reports)
        self._active_tab = "reports"

        # State
        self._report_views: list[dict] = []
        self._report_records: list[dict] = []
        self._report_table_choice = ctk.StringVar(value="Bank Transactions")
        self._report_view_choice = ctk.StringVar(value="")
        self._report_shared_url = ctk.StringVar(value="")

        container = ctk.CTkScrollableFrame(self.main_frame, fg_color=BG_DARK)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            container, text="📊  Generate Reports",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            container,
            text="Select a table and view from Airtable, then generate an Excel report\n"
                 "with clickable links your accountant can use to access records.",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM, justify="left",
        ).pack(anchor="w", pady=(0, 20))

        # --- Step 1: Table + View selection ---
        step1 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=10)
        step1.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            step1, text="1️⃣  Select Table & View",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(step1, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(row1, text="Table:", font=ctk.CTkFont(size=13), text_color=TEXT).pack(side="left", padx=(0, 8))
        self.report_table_menu = ctk.CTkOptionMenu(
            row1, values=["Bank Transactions", "Invoices"],
            variable=self._report_table_choice,
            width=200, height=32,
            fg_color="#333355", button_color=ACCENT,
            command=lambda _: self._load_views_for_report(),
        )
        self.report_table_menu.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(row1, text="View:", font=ctk.CTkFont(size=13), text_color=TEXT).pack(side="left", padx=(0, 8))
        self.report_view_menu = ctk.CTkOptionMenu(
            row1, values=["Loading..."],
            variable=self._report_view_choice,
            width=250, height=32,
            fg_color="#333355", button_color=ACCENT,
        )
        self.report_view_menu.pack(side="left")

        # --- Step 2: Shared view URL ---
        step2 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=10)
        step2.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            step2, text="2️⃣  Shared View URL (for clickable links)",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            step2,
            text="Paste the shared view link from Airtable (Share view → Copy link).\n"
                 "This makes links in the report clickable for your accountant.",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self.report_url_entry = ctk.CTkEntry(
            step2, textvariable=self._report_shared_url,
            width=500, height=34,
            fg_color="#1E1E2E", border_color="#555566",
            placeholder_text="https://airtable.com/shrXXXXXXXXXXXX",
            font=ctk.CTkFont(size=12),
        )
        self.report_url_entry.pack(anchor="w", padx=16, pady=(0, 12))

        # --- Step 3: Preview + Generate ---
        step3 = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=10)
        step3.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            step3, text="3️⃣  Preview & Generate",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT,
        ).pack(anchor="w", padx=16, pady=(12, 8))

        btn_row = ctk.CTkFrame(step3, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))

        self.btn_preview_report = ctk.CTkButton(
            btn_row, text="🔍  Preview Records", width=200, height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, hover_color="#1D4ED8",
            command=self._preview_report_records,
        )
        self.btn_preview_report.pack(side="left", padx=(0, 12))

        self.btn_generate_report = ctk.CTkButton(
            btn_row, text="📥  Generate Excel Report", width=240, height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=SUCCESS, hover_color="#15803D",
            command=self._generate_report,
            state="disabled",
        )
        self.btn_generate_report.pack(side="left")

        # Progress / status
        self.report_progress = ctk.CTkProgressBar(step3, width=500, height=12)
        self.report_progress.pack(padx=16, pady=(0, 4))
        self.report_progress.set(0)

        self.lbl_report_status = ctk.CTkLabel(
            step3, text="Select a table and view, then click Preview.",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
        )
        self.lbl_report_status.pack(anchor="w", padx=16, pady=(0, 12))

        # Preview area
        self.report_preview_frame = ctk.CTkFrame(container, fg_color=BG_DARK)
        self.report_preview_frame.pack(fill="both", expand=True)

        # Auto-load views
        self._load_views_for_report()

    def _load_views_for_report(self):
        table_name = self._report_table_choice.get()
        self.report_view_menu.configure(values=["Loading..."])
        self._report_view_choice.set("Loading...")

        def _worker():
            from src.airtable_client import fetch_views_for_table, get_table_ids
            try:
                table_ids = get_table_ids()
                table_id = table_ids.get(table_name, "")
                views = fetch_views_for_table(table_id)
                self._report_views = views
                names = [v["name"] for v in views] if views else ["(no views found)"]
                self.after(0, lambda: self.report_view_menu.configure(values=names))
                self.after(0, lambda: self._report_view_choice.set(names[0]))
            except Exception as e:
                self.after(0, lambda: self._report_view_choice.set(f"Error: {e}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _preview_report_records(self):
        table_name = self._report_table_choice.get()
        view_name = self._report_view_choice.get()
        if not view_name or view_name.startswith("(") or view_name.startswith("Error") or view_name == "Loading...":
            messagebox.showwarning("No View", "Please select a valid view first.")
            return

        self.btn_preview_report.configure(state="disabled", text="⏳  Loading...")
        self.btn_generate_report.configure(state="disabled")
        self.report_progress.set(0)
        self.lbl_report_status.configure(text="Fetching records from Airtable...", text_color=TEXT_DIM)

        # Clear preview
        for w in self.report_preview_frame.winfo_children():
            w.destroy()

        def _worker():
            from src.airtable_client import fetch_records_by_view, get_table_ids
            try:
                table_ids = get_table_ids()
                table_id = table_ids.get(table_name, "")
                records = fetch_records_by_view(table_id, view_name)
                self._report_records = records
                self.after(0, lambda: self._render_report_preview(records, table_name))
            except Exception as e:
                self.after(0, lambda: self.lbl_report_status.configure(
                    text=f"❌ Error: {e}", text_color=ERROR
                ))
            finally:
                self.after(0, lambda: self.btn_preview_report.configure(
                    state="normal", text="🔍  Preview Records"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _render_report_preview(self, records: list[dict], table_name: str):
        self.report_progress.set(1.0)

        if not records:
            self.lbl_report_status.configure(text="ℹ️ No records found in this view.", text_color=TEXT_DIM)
            return

        self.lbl_report_status.configure(
            text=f"✅ {len(records)} record(s) loaded. Review below, then Generate.",
            text_color=SUCCESS,
        )
        self.btn_generate_report.configure(state="normal")

        frame = self.report_preview_frame

        if table_name == "Bank Transactions":
            cols = [("Date", 100), ("Description", 220), ("Amount", 100), ("Type", 80), ("Matched", 80)]
        else:
            cols = [("Business", 180), ("Invoice #", 120), ("Date", 100), ("Total", 110), ("Matched", 80)]

        # Header
        hdr = ctk.CTkFrame(frame, fg_color="#333355", corner_radius=6)
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        for col_text, w in cols:
            ctk.CTkLabel(
                hdr, text=col_text, width=w,
                font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT,
            ).pack(side="left", padx=6, pady=6)

        # Show first 50 records max in preview
        for i, rec in enumerate(records[:50]):
            f = rec.get("fields", {})
            row = ctk.CTkFrame(frame, fg_color=BG_CARD if i % 2 == 0 else "#2E2E40", corner_radius=4)
            row.pack(fill="x", padx=10, pady=1)

            if table_name == "Bank Transactions":
                matched = f.get("Matched Invoice", [])
                match_text = f"✅ {len(matched)}" if matched else "❌"
                vals = [
                    (str(f.get("Date", "")), 100),
                    (str(f.get("Description", ""))[:30], 220),
                    (f"€{float(f.get('Amount', 0) or 0):.2f}", 100),
                    (str(f.get("Type", "")), 80),
                    (match_text, 80),
                ]
            else:
                linked = f.get("Bank Transactions", [])
                match_text = f"✅ {len(linked)}" if linked else "❌"
                total_raw = f.get("Total Invoice Including VAT", "")
                vals = [
                    (str(f.get("Business Name", ""))[:25], 180),
                    (str(f.get("Invoice Number", "")), 120),
                    (str(f.get("Date Of Invoice", "")), 100),
                    (str(total_raw), 110),
                    (match_text, 80),
                ]

            for val, w in vals:
                ctk.CTkLabel(
                    row, text=val, width=w,
                    font=ctk.CTkFont(size=11), text_color=TEXT,
                ).pack(side="left", padx=6, pady=5)

        if len(records) > 50:
            ctk.CTkLabel(
                frame, text=f"... and {len(records) - 50} more records (all will be in the report)",
                font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
            ).pack(anchor="w", padx=16, pady=6)

    def _generate_report(self):
        if not self._report_records:
            messagebox.showwarning("No Data", "Preview records first.")
            return

        table_name = self._report_table_choice.get()
        view_name = self._report_view_choice.get()
        shared_url = self._report_shared_url.get().strip().rstrip("/")

        # Ask for save location
        safe_view = "".join(c if c.isalnum() or c in " -_" else "_" for c in view_name)
        default_name = f"{table_name} - {safe_view}.xlsx"
        filepath = filedialog.asksaveasfilename(
            title="Save Report As",
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx")],
            initialfile=default_name,
        )
        if not filepath:
            return

        self.btn_generate_report.configure(state="disabled", text="⏳  Generating...")
        self.report_progress.set(0)
        self.lbl_report_status.configure(text="Fetching linked records...", text_color=TEXT_DIM)

        def _worker():
            from src.airtable_client import fetch_linked_records, get_table_ids
            from src.report_generator import generate_bank_txn_report, generate_invoice_report
            import os as _os

            try:
                table_ids = get_table_ids()
                records = self._report_records

                self.after(0, lambda: self.report_progress.set(0.3))

                if table_name == "Bank Transactions":
                    # Collect all linked invoice IDs
                    inv_ids = set()
                    for rec in records:
                        linked = rec.get("fields", {}).get("Matched Invoice", [])
                        for x in (linked if isinstance(linked, list) else []):
                            inv_ids.add(x if isinstance(x, str) else x.get("id", ""))
                    inv_ids.discard("")

                    self.after(0, lambda: self.lbl_report_status.configure(
                        text=f"Fetching {len(inv_ids)} linked invoice(s)...", text_color=TEXT_DIM
                    ))

                    linked_invoices = fetch_linked_records(
                        table_ids.get("Invoices", ""), list(inv_ids)
                    ) if inv_ids else {}

                    self.after(0, lambda: self.report_progress.set(0.7))
                    self.after(0, lambda: self.lbl_report_status.configure(
                        text="Generating Excel file...", text_color=TEXT_DIM
                    ))

                    out = generate_bank_txn_report(
                        records=records,
                        linked_invoices=linked_invoices,
                        shared_view_url=shared_url,
                        output_path=filepath,
                        report_title=f"{table_name} – {view_name}",
                    )
                else:
                    # Collect all linked bank txn IDs
                    txn_ids = set()
                    for rec in records:
                        linked = rec.get("fields", {}).get("Bank Transactions", [])
                        for x in (linked if isinstance(linked, list) else []):
                            txn_ids.add(x if isinstance(x, str) else x.get("id", ""))
                    txn_ids.discard("")

                    self.after(0, lambda: self.lbl_report_status.configure(
                        text=f"Fetching {len(txn_ids)} linked transaction(s)...", text_color=TEXT_DIM
                    ))

                    linked_txns = fetch_linked_records(
                        table_ids.get("Bank Transactions", ""), list(txn_ids)
                    ) if txn_ids else {}

                    self.after(0, lambda: self.report_progress.set(0.7))
                    self.after(0, lambda: self.lbl_report_status.configure(
                        text="Generating Excel file...", text_color=TEXT_DIM
                    ))

                    out = generate_invoice_report(
                        records=records,
                        linked_bank_txns=linked_txns,
                        shared_view_url=shared_url,
                        output_path=filepath,
                        report_title=f"{table_name} – {view_name}",
                    )

                self.after(0, lambda: self.report_progress.set(1.0))
                self.after(0, lambda: self.lbl_report_status.configure(
                    text=f"✅ Report saved to: {out}", text_color=SUCCESS
                ))

                # Open the file
                try:
                    _os.startfile(str(out))
                except Exception:
                    pass

            except Exception as e:
                self.after(0, lambda: self.lbl_report_status.configure(
                    text=f"❌ Error: {e}", text_color=ERROR
                ))
            finally:
                self.after(0, lambda: self.btn_generate_report.configure(
                    state="normal", text="📥  Generate Excel Report"
                ))

        threading.Thread(target=_worker, daemon=True).start()

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
    # Sync Airtable (refresh current tab)
    # ------------------------------------------------------------------

    def _sync_airtable(self):
        """Re-fetch data from Airtable and refresh the current tab."""
        self.btn_sync.configure(state="disabled", text="⏳  Syncing...")

        tab_map = {
            "upload": self._show_upload_tab,
            "history": self._show_history_tab,
            "browse": self._show_browse_tab,
            "bank": self._show_bank_tab,
            "match": self._show_match_tab,
            "reports": self._show_reports_tab,
        }

        show_fn = tab_map.get(self._active_tab, self._show_browse_tab)

        # Invalidate cached Airtable table handle so fresh data is fetched
        import src.airtable_client as _ac
        _ac._cached_table = None

        try:
            show_fn()
        finally:
            self.btn_sync.configure(state="normal", text="🔄  Sync Airtable")

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
