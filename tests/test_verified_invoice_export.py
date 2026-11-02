"""Second cumulative invoice feed after MDM and contract verification."""
import csv
import io
import zipfile
from dataclasses import replace
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import load_workbook

import web_app
from models.invoice_schema import Invoice, InvoiceResult, LineItem
from services.local_storage import LocalStorage
from services.mdm_csv_service import (COLUMNS, VERIFIED_COLUMNS, VERIFIED_REPORT_NAME,
                                      generate_mdm_csv, generate_verified_csv)
from services.vendor_matching import load_vendor_accounts


def _rows(data: bytes):
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def _catalog(root):
    folder = root / 'MDM'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'vendor_accounts.csv').write_text(
        'Account,Vendor,Restricted To\nCON-01,Blue Ocean Technologies LLC,APAC\n', encoding='utf-8')
    contract = folder / 'contracts.csv'
    contract.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,2030-12-31\n',
                        encoding='utf-8')
    return contract


def _result(number, *, reviewed=False):
    return InvoiceResult(
        invoice=Invoice(vendor_name='Blue Ocean Technologies LLC', region='APAC',
                        invoice_number=number, invoice_date='2026-10-01', currency='USD',
                        service_start_date='2026-10-01', service_end_date='2026-10-31',
                        subtotal='4500.00', tax_amount='0.00', total_amount='4500.00'),
        line_items=[LineItem(description='Non-Display Fee', quantity=1, line_total='2500.00'),
                    LineItem(description='Distribution Fee', quantity=1, line_total='2000.00')],
        processed_at='2026-10-05T00:00:00+00:00',
        validation_status='REVIEW_REQUIRED' if reviewed else 'VALID',
        review_required=reviewed,
    )


def test_verified_feed_schema_mapping_and_review_gate(tmp_path):
    contract = _catalog(tmp_path)
    accounts = load_vendor_accounts(tmp_path / 'MDM' / 'vendor_accounts.csv', contract)
    data = generate_verified_csv([_result('BOT-1'), _result('BOT-2', reviewed=True)], accounts)
    rows = _rows(data)
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == VERIFIED_COLUMNS
    assert row == {
        'Insert or Update': 'Insert', 'Vendor': 'Blue Ocean Technologies LLC',
        'Billing Account': 'CON-01', 'Invoice Number': 'BOT-1',
        'Invoice Date': '10/01/2026', 'Currency': 'USD',
        'Start Date': '10/01/2026', 'End Date': '10/31/2026',
        'Net Amount': '4500.0', 'Tax Amount': '0.0',
        'Description': 'Non-Display Fee; Distribution Fee',
        'Date Entered': '10/05/2026', 'Approved On Date': '10/05/2026',
    }
    contract.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,\n', encoding='utf-8')
    invalid_accounts = load_vendor_accounts(tmp_path / 'MDM' / 'vendor_accounts.csv', contract)
    assert _rows(generate_verified_csv([_result('BOT-1')], invalid_accounts)) == []


def test_expired_contract_rejected_and_approved_excel_contains_only_active_contracts(tmp_path):
    contract = _catalog(tmp_path)
    store = LocalStorage(tmp_path)
    store.save_batch(uuid4().hex, [_result('BOT-1')])
    active_book = load_workbook(io.BytesIO(store.report_files()['Approved_Invoices.xlsx']), read_only=True)
    assert active_book.sheetnames == ['Contract Verified']
    assert active_book['Contract Verified'].max_row == 2
    active_book.close()

    contract.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,2025-12-31\n',
                        encoding='utf-8')
    assert store.refresh_exports() == []
    reports = store.report_files()
    assert _rows(reports['MDM/Contract_verified_invoices.csv']) == []
    approved_book = load_workbook(io.BytesIO(reports['Approved_Invoices.xlsx']), read_only=True)
    assert approved_book.sheetnames == ['Contract Verified']
    assert approved_book['Contract Verified'].max_row == 1
    approved_book.close()
    audit_book = load_workbook(io.BytesIO(reports['Invoice_History.xlsx']), read_only=True)
    assert audit_book['MDM Invoice Data'].max_row == 1
    audit_book.close()


def test_invoice_data_csv_contains_only_successful_active_contracts(tmp_path):
    contract = _catalog(tmp_path)
    accounts = load_vendor_accounts(tmp_path / 'MDM' / 'vendor_accounts.csv', contract)
    good = _result('GOOD')
    good.mdm_checked = True
    review = _result('REVIEW', reviewed=True)
    review.mdm_checked = True
    pending = _result('PENDING')
    pending.mdm_checked = False
    assert [row['Invoice Number'] for row in _rows(generate_mdm_csv([good, review, pending], accounts, success_only=True))] == ['GOOD']
    contract.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,2025-12-31\n',
                        encoding='utf-8')
    expired_accounts = load_vendor_accounts(tmp_path / 'MDM' / 'vendor_accounts.csv', contract)
    assert _rows(generate_mdm_csv([good], expired_accounts, success_only=True)) == []


def test_verified_csv_and_excel_use_mdm_vendor_without_overwriting_source(tmp_path):
    _catalog(tmp_path)
    store = LocalStorage(tmp_path)
    result = _result('BOT-CANONICAL')
    result.invoice.vendor_name = 'Blue Ocean Technologies, LLC'
    original = result.invoice.to_dict().copy()
    master_path = tmp_path / 'MDM' / 'vendor_accounts.csv'
    master_before = master_path.read_bytes()
    batch_id = uuid4().hex
    store.save_batch(batch_id, [result])

    assert _rows((tmp_path / 'MDM' / 'Invoice_data.csv').read_bytes())[0]['Vendor -As per MDM'] == 'Blue Ocean Technologies LLC'
    assert _rows((tmp_path / VERIFIED_REPORT_NAME).read_bytes())[0]['Vendor'] == 'Blue Ocean Technologies LLC'
    book = load_workbook(io.BytesIO(store.report_files()['Invoice_History.xlsx']), read_only=True)
    assert book['MDM Invoice Data'].cell(2, 1).value == 'Blue Ocean Technologies LLC'
    assert book['Contract Verified'].cell(2, 2).value == 'Blue Ocean Technologies LLC'
    book.close()
    assert store.load_batches()[0][1][0].invoice.to_dict() == original
    assert master_path.read_bytes() == master_before


def test_short_master_name_and_ocr_typo_use_exact_region_selected_vendor_in_all_final_exports(tmp_path, monkeypatch):
    _catalog(tmp_path)
    master_path = tmp_path / 'MDM' / 'vendor_accounts.csv'
    master_path.write_text('Account,Vendor,Restricted To\n'
                           'CON-01,Blue ocean,APAC\nCON-02,BLUE OCEAN,EMEA\n', encoding='utf-8')
    master_before = master_path.read_bytes()
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(tmp_path)))
    result = _result('BOT-SHORT-MASTER')
    result.invoice.vendor_name = 'Blur OCean Technologies LLC'
    result.invoice.region = 'Singapore'
    original = result.invoice.to_dict().copy()
    store = LocalStorage(tmp_path)
    batch_id = uuid4().hex
    assert store.save_batch(batch_id, [result]) == []
    client = TestClient(web_app.app)
    response = client.post('/api/mdm/run', json={'batch_id': batch_id, 'generation': store.generation})
    assert response.status_code == 200, response.text
    row = response.json()['results'][0]['mdm_row']
    assert row['Vendor -As per MDM'] == 'Blue ocean'
    assert row['Billing Account'] == 'CON-01'
    assert row['Review status'] == 'SUCCESS'
    assert response.json()['results'][0]['invoice'] == original
    reports = store.report_files()
    assert _rows(reports['MDM/Invoice_data.csv'])[0]['Vendor -As per MDM'] == 'Blue ocean'
    assert _rows(reports[VERIFIED_REPORT_NAME])[0]['Vendor'] == 'Blue ocean'
    assert _rows(client.get(f'/api/download/batch/{batch_id}/{VERIFIED_REPORT_NAME}').content)[0]['Vendor'] == 'Blue ocean'
    book = load_workbook(io.BytesIO(reports['Invoice_History.xlsx']), read_only=True)
    assert book['MDM Invoice Data'].cell(2, 1).value == 'Blue ocean'
    assert book['Contract Verified'].cell(2, 2).value == 'Blue ocean'
    book.close()
    assert store.load_batches()[0][1][0].invoice.to_dict() == original
    assert master_path.read_bytes() == master_before


def test_second_cumulative_file_rebuilds_with_history_and_resets(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    _catalog(root)
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    store = LocalStorage(root)
    first_id = uuid4().hex
    store.save_batch(first_id, [_result('BOT-1')])
    store.save_batch(uuid4().hex, [_result('BOT-2')])
    verified = root / VERIFIED_REPORT_NAME
    original = root / 'MDM' / 'Invoice_data.csv'
    assert [row['Invoice Number'] for row in _rows(verified.read_bytes())] == ['BOT-1', 'BOT-2']
    assert [row['Invoice Number'] for row in _rows(original.read_bytes())] == ['BOT-1', 'BOT-2']
    store.refresh_exports()
    assert len(_rows(verified.read_bytes())) == 2
    assert list(_rows(original.read_bytes())[0]) == COLUMNS

    book = load_workbook(io.BytesIO(store.report_files()['Invoice_History.xlsx']), read_only=True)
    assert book['Contract Verified'].max_row == 3
    book.close()

    client = TestClient(web_app.app)
    assert _rows(client.get(f'/api/download/batch/{first_id}/{VERIFIED_REPORT_NAME}').content)[0]['Invoice Number'] == 'BOT-1'
    archive = zipfile.ZipFile(io.BytesIO(client.get(f'/api/download/batch/{first_id}/invoice_results.zip').content))
    assert VERIFIED_REPORT_NAME in archive.namelist()
    assert len(_rows(client.get(f'/api/download/history/{VERIFIED_REPORT_NAME}').content)) == 2

    store.reset(str(store.root))
    assert _rows(verified.read_bytes()) == []
    assert _rows(original.read_bytes()) == []
    assert next(csv.reader(io.StringIO(verified.read_text(encoding='utf-8-sig')))) == VERIFIED_COLUMNS
