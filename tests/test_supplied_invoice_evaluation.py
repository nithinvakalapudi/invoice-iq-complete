"""Ensure offline invoice reports score real references and preserve live data."""
from dataclasses import replace
import io
import json
import zipfile
from uuid import uuid4

import pytest

from evaluation import supplied_invoices as evaluator
from models.invoice_schema import Invoice, InvoiceResult, LineItem
from services.local_storage import LocalStorage
from services.validation_service import validate_invoice


def _result(number='TEST-1'):
    invoice = Invoice(invoice_number=number, vendor_name='Example Vendor', region='APAC',
                      invoice_date='2026-10-01', currency='USD', subtotal=100, tax_amount=10,
                      total_amount=110, service_start_date='2026-10-01', service_end_date='2026-10-31')
    return InvoiceResult(invoice=invoice, line_items=[LineItem(description='Service', quantity=1,
                                                              unit_price=100, line_total=100)],
                         validation_status='VALID', review_required=False,
                         field_confidence={key: 99 for key in invoice.to_dict()},
                         source_file=number + '.pdf', processed_at='2026-10-10T00:00:00Z')


def test_reference_comparison_does_not_score_unknown_or_invalid_labels_as_correct():
    scores = evaluator.compare({'vendor_name': 'example vendor', 'currency': '',
                                'invoice_date': 'not a date', 'subtotal': '100.00'}, _result())
    assert {score['field'] for score in scores} == {'vendor_name', 'subtotal'}
    assert all(score['correct'] for score in scores)
    wrong = _result()
    wrong.invoice.total_amount = None
    assert evaluator.compare({'total_amount': '110.00'}, wrong)[0]['correct'] is False


def test_service_date_reference_comes_only_from_explicit_answer_sheet_service_period():
    fields, items = evaluator._reference({
        'line_items': '10/01/26 - 10/31/26 | Service | 1 | 100.00 | 100.00'})
    assert fields['service_start_date'] == '2026-10-01'
    assert fields['service_end_date'] == '2026-10-31'
    assert items == [{'description': 'Service', 'quantity': '1', 'unit_price': '100.00', 'line_total': '100.00'}]
    fields, items = evaluator._reference({'invoice_date': '2026-10-01',
                                         'line_items': 'Service | qty=1 | rate=100.00 | amount=100.00'})
    assert 'service_start_date' not in fields and 'service_end_date' not in fields
    assert items[0]['line_total'] == '100.00'


@pytest.mark.parametrize('period', ['01/10/26 - 31/10/26', '10/01/26 - 10/31/26',
                                  '2026-10-01 - 2026-10-31'])
def test_reference_service_range_uses_consistent_order_from_both_boundaries(period):
    assert evaluator._reference_period(period) == ['2026-10-01', '2026-10-31']


def test_conflicting_reference_date_orders_are_not_scored_as_truth():
    assert evaluator._reference_period('20/10/26 - 10/31/26') == []


def test_json_line_item_references_measure_every_printed_item_field():
    scores = evaluator.compare({'items_json': json.dumps([
        {'description': 'Service', 'quantity': 1, 'unit_price': 100.0, 'amount': 100.0}])}, _result())
    assert len(scores) == 5
    assert all(score['correct'] for score in scores)
    wrong = _result()
    wrong.line_items[0].quantity = 2
    assert next(score for score in evaluator.compare({'items_json': json.dumps([
        {'description': 'Service', 'quantity': 1, 'unit_price': 100, 'amount': 100}])}, wrong)
                if score['field'] == 'line_quantity')['correct'] is False


def _live_store(root):
    store = LocalStorage(root)
    folder = root / 'MDM'
    folder.mkdir(exist_ok=True)
    (folder / 'vendor_accounts.csv').write_text(
        'Account,Vendor,Restricted To\n00123,Example Vendor,APAC\n', encoding='utf-8')
    (folder / 'contracts.csv').write_text(
        'Contract ID,Start Date,End Date\n00123,2025-01-01,2025-12-31\n', encoding='utf-8')
    model_folder = root / 'models'
    model_folder.mkdir(exist_ok=True)
    (model_folder / 'preserved.bin').write_bytes(b'existing trained data')
    store.save_batch(uuid4().hex, [_result('LIVE')])
    return store


@pytest.mark.parametrize('large_archive', [False, True])
def test_regression_is_isolated_and_does_not_run_uploaded_scripts(tmp_path, monkeypatch, large_archive):
    live = _live_store(tmp_path / 'live')
    monkeypatch.setattr(evaluator, 'settings', replace(evaluator.settings, local_storage_dir=str(live.root)))
    monkeypatch.setattr(evaluator, '_pilot', lambda: None)
    monkeypatch.setattr(evaluator, '_reviewed_model', lambda: None)
    def extract(document, tolerance, threshold):
        if document.filename == 'broken.pdf':
            return InvoiceResult.failed(document.filename, 'Incomplete test document', '2026-10-10T00:00:00Z')
        result = _result(document.filename)
        if document.filename == 'missing.pdf':
            result.invoice.service_end_date = None
        return validate_invoice(result, tolerance, threshold)
    monkeypatch.setattr(evaluator, 'process_document', extract)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('train_model.py', "raise RuntimeError('Never execute this attached script')")
        if large_archive:
            for index in range(201):
                archive.writestr(f'invoices/test-{index}.pdf', b'%PDF fixture')
        else:
            archive.writestr('ground_truth_answer_sheet.csv',
                             'source_file,vendor_name,total_amount\nvalid.pdf,Example Vendor,110\n')
            archive.writestr('valid.pdf', b'%PDF fixture')
            archive.writestr('missing.pdf', b'%PDF fixture')
            archive.writestr('broken.pdf', b'broken')
    source = tmp_path / 'supplied.zip'
    source.write_bytes(payload.getvalue())
    before = evaluator._fingerprint(live)
    output = tmp_path / 'reports'
    report = evaluator.run([source], output, workers=2)
    assert evaluator._fingerprint(live) == before
    assert (output / 'Invoice_Test_Results.xlsx').is_file()
    assert (output / 'Invoice_Test_Report.md').is_file()
    assert (output / 'MDM' / 'Invoice_data.csv').is_file()
    if large_archive:
        assert report['archive_entries'] == 201
        assert report['verified_export_rows'] == 0  # Fixture contracts ended in 2025.
        assert b'UI_LIMIT_BLOCKED_AS_EXPECTED' in (output / 'Archive_Intake_Checks.csv').read_bytes()
    else:
        assert report['archive_entries'] == 3
        assert report['status_counts'] == {'REJECTED': 2, 'FAILED': 1}
        assert report['processing_status_counts']['FAILED'] == 1
        assert report['core_field_accuracy_percent'] == 100
        assert report['verified_export_rows'] == 0
    def no_new_extraction(*args):
        raise AssertionError('A report-only replay must not run model inference')
    monkeypatch.setattr(evaluator, 'process_document', no_new_extraction)
    replay = evaluator.run([source], tmp_path / 'replayed', predictions_from=output / 'Predictions.json')
    assert replay['status_counts'] == report['status_counts']
    assert replay['run_mode'] == 'REPORT_REPLAY'
    with pytest.raises(FileExistsError):
        evaluator.run([source], output)
