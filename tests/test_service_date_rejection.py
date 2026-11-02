"""Missing service dates reject invoices across intake, review and exports."""
import csv
import io
import zipfile
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import web_app
from models.invoice_schema import Invoice, InvoiceResult, LineItem
from services import document_processing
from services.csv_service import generate_csvs
from services.duplicate_service import mark_duplicates
from services.local_storage import LocalStorage
from services.mdm_csv_service import COLUMNS, generate_mdm_csv, generate_verified_csv, mdm_row
from services.tabular_intake import import_invoice_rows
from services.validation_service import service_date_rejection_reason, validate_invoice
from services.vendor_matching import VendorAccount
from test_msg_uploads import msg_bytes
from utils.file_utils import expand_upload


def _result(number='SERVICE-1'):
    invoice = Invoice(vendor_name='Example Vendor', invoice_number=number,
                      invoice_date='2026-10-01', currency='USD',
                      service_start_date='2026-10-01', service_end_date='2026-10-31',
                      subtotal=100, tax_amount=5, total_amount=105)
    return InvoiceResult(invoice=invoice,
                         line_items=[LineItem(description='Service', quantity=1,
                                              unit_price=100, line_total=100)],
                         field_confidence={key: 99 for key in invoice.to_dict()},
                         validation_status='VALID', review_required=False,
                         processed_at='2026-10-10T00:00:00Z', source_file='invoice.pdf')


def _accounts():
    return [VendorAccount('CON-01', 'Example Vendor', '', contract_status='PRESENT',
                          contract_start_date='2026-01-01', contract_end_date='2026-12-31')]


def _rows(data):
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def _catalog(root):
    folder = root / 'MDM'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'vendor_accounts.csv').write_text(
        'Account,Vendor,Restricted To\nCON-01,Example Vendor,\n', encoding='utf-8')
    (folder / 'contracts.csv').write_text(
        'Contract ID,Start Date,End Date\nCON-01,2026-01-01,2026-12-31\n', encoding='utf-8')


@pytest.mark.parametrize('field,label', [('service_start_date', 'Billing Start Date'),
                                        ('service_end_date', 'Billing End Date')])
@pytest.mark.parametrize('missing', [None, '', '   ', 'null', 'NULL', 'None', 'NaN', 'NaT'])
def test_missing_service_boundary_rejects_even_high_confidence(field, label, missing):
    result = _result()
    setattr(result.invoice, field, missing)
    original_amount = result.invoice.total_amount
    validate_invoice(result, .02, 95)
    assert result.validation_status == 'REJECTED'
    assert result.review_required is True
    assert result.extraction_confidence == 99
    assert label in service_date_rejection_reason(result)
    assert any('Invoice rejected: missing Service Date' in error for error in result.errors)
    assert result.invoice.total_amount == original_amount
    assert getattr(result.invoice, field) == missing  # Never invent a replacement date.


def test_both_missing_dates_explained_and_correction_restores_normal_validation():
    result = _result()
    result.invoice.service_start_date = result.invoice.service_end_date = None
    validate_invoice(result, .02, 95)
    assert 'Billing Start Date, Billing End Date' in service_date_rejection_reason(result)
    result.invoice.service_start_date = '10/01/2026'
    validate_invoice(result, .02, 95)
    assert result.validation_status == 'REJECTED'
    assert 'Billing End Date' in service_date_rejection_reason(result)
    result.invoice.service_end_date = '10/31/2026'
    validate_invoice(result, .02, 95)
    assert result.validation_status == 'VALID'
    assert result.review_required is False
    assert result.errors == []
    result.invoice.total_amount = 106
    validate_invoice(result, .02, 95)
    assert result.validation_status == 'REVIEW_REQUIRED'  # Other problems still require review.


@pytest.mark.parametrize('processing,status', [('FAILED', 'FAILED'), ('SKIPPED', 'SKIPPED')])
def test_failed_and_skipped_intake_not_relabelled_as_service_date_rejection(processing, status):
    result = InvoiceResult(processing_status=processing, validation_status=status)
    assert service_date_rejection_reason(result) == ''
    assert web_app._result_payload(result)['validation_status'] == status


@pytest.mark.parametrize('flag', [None, '_local_draft', '_ocr_only'])
def test_rejection_remains_dominant_over_document_processing_overrides(monkeypatch, flag):
    result = _result()
    result.invoice.service_end_date = None
    payload = {'invoice': result.invoice.to_dict(), 'line_items': [line.to_dict() for line in result.line_items],
               'field_confidence': result.field_confidence, '_confidence_calibrated': True}
    if flag:
        payload[flag] = True
    monkeypatch.setattr(document_processing, 'extract_invoice', lambda *_: payload)
    document = expand_upload('invoice.pdf', b'%PDF fixture', 1_000_000)[0]
    processed = document_processing.process_document(document, .02, 95)
    assert processed.validation_status == 'REJECTED'
    assert mdm_row(processed, _accounts())['Action'] == 'Rejected'


def test_duplicate_detection_cannot_downgrade_rejection():
    first, second = _result(), _result()
    first.invoice.service_start_date = second.invoice.service_end_date = None
    for result in mark_duplicates([first, second]):
        assert result.duplicate_status == 'POSSIBLE_DUPLICATE'
        assert result.validation_status == 'REJECTED'
    assert mark_duplicates([first], [_result()])[0].validation_status == 'REJECTED'


def test_old_valid_record_is_rejected_at_payload_counts_and_exports_without_mutation():
    rejected = _result('OLD-VALID')
    rejected.invoice.service_start_date = None
    before = rejected.invoice.to_dict().copy()
    row = mdm_row(rejected, _accounts())
    assert row['Review status'] == 'REJECTED'
    assert row['Action'] == 'Rejected'
    assert row['Billing Account'] == 'CON-01'
    assert 'Billing Start Date' in row['Comments']
    assert 'Invoice rejected' in row['Review reasons']
    counts = web_app._counts([rejected, _result('VALID')], _accounts())
    assert counts['rejected'] == 1
    assert counts['auto_approved'] == 1
    assert counts['review'] == 0
    payload = web_app._result_payload(rejected, _accounts())
    assert payload['validation_status'] == 'REJECTED'
    assert payload['review_required'] is True
    assert 'Invoice rejected' in payload['errors'][0]
    mdm = _rows(generate_mdm_csv([rejected], _accounts()))[0]
    assert list(mdm) == COLUMNS  # Preserve the configured 16-column MDM schema.
    assert 'Invoice rejected' in mdm['Comments']
    reports = generate_csvs([rejected])
    assert _rows(reports['Invoice_Data.csv'])[0]['Status'] == 'REJECTED'
    audit = _rows(reports['Audit_Report.csv'])[0]
    assert audit['validation_status'] == 'REJECTED'
    assert audit['review_required'] == 'True'
    assert 'Service Date' in audit['errors']
    verified = _rows(generate_verified_csv([rejected, _result('VALID')], _accounts()))
    assert [entry['Invoice Number'] for entry in verified] == ['VALID']
    assert rejected.invoice.to_dict() == before
    assert rejected.validation_status == 'VALID'  # Export guards do not rewrite stored extraction.


def test_refresh_saved_excel_and_csv_retains_rejected_rows_but_excludes_verified(tmp_path):
    root = tmp_path / 'local_data'
    store = LocalStorage(root)
    master = root / 'MDM' / 'vendor_accounts.csv'
    master.parent.mkdir(exist_ok=True)
    master.write_text('Account,Vendor,Restricted To\nCON-01,Example Vendor,\n', encoding='utf-8')
    contract = root / 'MDM' / 'contracts.csv'
    contract.write_text('Contract ID,Start Date,End Date\nCON-01,2026-01-01,2026-12-31\n', encoding='utf-8')
    models = root / 'models'
    models.mkdir(exist_ok=True)
    model = models / 'preserved.joblib'
    model.write_bytes(b'trained model stays untouched')
    rejected = _result('REJECTED-1')
    rejected.invoice.service_end_date = None
    batch_id = uuid4().hex
    assert store.save_batch(batch_id, [rejected, _result('VALID-1')]) == []
    source_before = [item.invoice.to_dict() for item in store.load_batches()[0][1]]
    master_before, contract_before, model_before = master.read_bytes(), contract.read_bytes(), model.read_bytes()
    assert store.refresh_exports() == []
    assert store.count() == (1, 2)
    reports = store.report_files()
    assert len(_rows(reports['MDM/Invoice_data.csv'])) == 1
    assert len(_rows(reports['MDM/Contract_verified_invoices.csv'])) == 1
    book = load_workbook(io.BytesIO(reports['Invoice_History.xlsx']), read_only=True)
    assert book['MDM Invoice Data'].max_row == 2
    assert book['Contract Verified'].max_row == 2
    audit = book['Audit_Report']
    audit_rows = list(audit.values)
    assert audit_rows[1][audit_rows[0].index('validation_status')] == 'REJECTED'
    book.close()
    assert [item.invoice.to_dict() for item in store.load_batches()[0][1]] == source_before
    assert (master.read_bytes(), contract.read_bytes(), model.read_bytes()) == (master_before, contract_before, model_before)


def test_import_with_service_dates_still_reviews_but_missing_dates_reject():
    data = b'Invoice,Vendor,Currency,Invoice Amount,Billing Start Date,Billing End Date\nOK,Vendor,USD,100,2026-10-01,2026-10-31\nBAD,Vendor,USD,100,2026-10-01,\n'
    valid_dates, missing_date = import_invoice_rows('import.csv', data, .02, 95)
    assert valid_dates.validation_status == 'REVIEW_REQUIRED'
    assert missing_date.validation_status == 'REJECTED'
    assert valid_dates.processing_status == missing_date.processing_status == 'IMPORTED'


def test_msg_multiple_attachments_are_rejected_or_accepted_independently(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    _catalog(root)
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    seen = []
    def extract(data, name):
        seen.append((data, name))
        result = _result(name)
        if name == 'missing-date.pdf':
            result.invoice.service_end_date = None
        return {'invoice': result.invoice.to_dict(), 'line_items': [item.to_dict() for item in result.line_items],
                'field_confidence': result.field_confidence}
    monkeypatch.setattr(document_processing, 'extract_invoice', extract)
    mail = msg_bytes([{'name': 'missing-date.pdf', 'data': b'%PDF without service end'},
                      {'name': 'dated.png', 'data': b'PNG with dates'},
                      {'name': 'signature.png', 'data': b'PRIVATE', 'hidden': 1}],
                     body='Service dates 2026-10-01 to 2026-10-31 in EMAIL BODY ONLY')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('mail.msg', mail)
    response = TestClient(web_app.app).post('/api/process', files=[
        ('files', ('mail.zip', archive.getvalue(), 'application/zip'))])
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch['counts']['total'] == 2
    assert batch['counts']['rejected'] == 1
    assert batch['counts']['auto_approved'] == 1
    assert batch['counts']['review'] == 0
    assert [item['validation_status'] for item in batch['results']] == ['REJECTED', 'VALID']
    assert all(item['source_email'] == 'mail.msg' for item in batch['results'])
    assert {name for _, name in seen} == {'missing-date.pdf', 'dated.png'}
    assert all(b'EMAIL BODY' not in data and data != b'PRIVATE' for data, _ in seen)
    assert len(_rows((root / 'MDM' / 'Contract_verified_invoices.csv').read_bytes())) == 0
    mdm = TestClient(web_app.app).post('/api/mdm/run', json={
        'batch_id': batch['batch_id'], 'generation': batch['generation'],
    })
    assert mdm.status_code == 200, mdm.text
    assert len(_rows((root / 'MDM' / 'Contract_verified_invoices.csv').read_bytes())) == 1


def test_human_review_cannot_accept_missing_dates_and_revalidates_after_correction(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    _catalog(root)
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    store = LocalStorage(root)
    result = _result()
    result.invoice.service_start_date = result.invoice.service_end_date = None
    batch_id = uuid4().hex
    store.save_batch(batch_id, [result])
    client = TestClient(web_app.app)
    def correct(fields):
        response = client.post(f'/api/batches/{batch_id}/review', json={
            'generation': store.generation, 'index': 0, 'fields': fields,
            'tolerance': .02, 'threshold': 95})
        assert response.status_code == 200, response.text
        return response.json()
    assert correct({'invoice_number': 'CORRECTED'})['results'][0]['validation_status'] == 'REJECTED'
    assert correct({'service_start_date': '2026-10-01'})['counts']['rejected'] == 1
    final = correct({'service_end_date': '2026-10-31'})
    assert final['counts']['rejected'] == 0
    assert final['results'][0]['mdm_row']['Review status'] == 'SUCCESS'
    assert final['results'][0]['errors'] == []
    assert final['results'][0]['mdm_row']['Comments'] == ''
    assert len(_rows((root / 'MDM' / 'Contract_verified_invoices.csv').read_bytes())) == 1
