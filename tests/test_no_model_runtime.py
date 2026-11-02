import subprocess
import sys

from models.invoice_schema import InvoiceResult
from services import local_extraction_service as local
from services.mdm_csv_service import mdm_row
from services.validation_service import validate_invoice


def test_application_starts_without_importing_model_packages():
    code = "import sys,web_app; assert not {'sklearn','joblib','ollama','torch','transformers','openai'}.intersection(sys.modules)"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_dates_are_kept_as_printed_without_model_inference(monkeypatch):
    monkeypatch.setattr(local, 'extract_document_text', lambda *_:
        'Vendor: Example Supplier LLC\nInvoice Number: INV-PRINTED\nInvoice Date: 03/08/2015\n'
        'Currency: GBP\nService Period\n03/08/2015 - 04/09/2015\nAmount Due: 100.00')
    monkeypatch.setattr(local, '_pilot', lambda: (_ for _ in ()).throw(AssertionError('Model loading is disabled')))
    payload = local.extract_invoice(b'PDF', 'invoice.pdf')
    result = InvoiceResult.from_ai_payload(payload, 'invoice.pdf', '2026-11-01T00:00:00Z')
    validate_invoice(result, .02, 95)
    row = mdm_row(result)
    assert row['Invoice Date'] == '03/08/2015'
    assert row['Billing Start Date'] == '03/08/2015'
    assert row['Billing End Date'] == '04/09/2015'
    assert row['Ageing (In Days)'] == ''
    assert not any('Invalid date' in error for error in result.errors)
