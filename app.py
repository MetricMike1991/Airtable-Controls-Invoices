"""
Airtable Invoice Uploader – Desktop application for uploading invoices
and populating the Invoices table in Airtable using OpenAI extraction.

Run:  python app.py
"""

from ui.main_window import InvoiceUploaderApp


def main():
    app = InvoiceUploaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
