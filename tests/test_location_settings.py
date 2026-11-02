"""Saved UI locations use real isolated files, never the live invoice history."""
import csv
import io
import json
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

import web_app
from config.ui_settings import UiSettings, load_ui_settings, settings_file
from models.invoice_schema import Invoice, InvoiceResult
from services.storage_lock import folder_operation_lock
from services.vendor_matching import catalog_paths, load_vendor_accounts
from test_msg_uploads import msg_bytes


def fake_invoice(document, tolerance, threshold):
    if document.intake_status:
        return InvoiceResult.failed(document.filename, document.intake_message, '2026-10-11T10:00:00Z')
    return InvoiceResult(invoice=Invoice(vendor_name='Example Vendor LLC', invoice_number=document.filename,
                                        invoice_date='2026-10-01', currency='USD', subtotal='15',
                                        tax_amount='0', total_amount='15', service_start_date='2026-10-01',
                                        service_end_date='2026-10-31', region='North America'),
                         source_file=document.filename, source_email=document.source_email,
                         source_attachment=document.source_attachment,
                         attachment_index=document.attachment_index,
                         processed_at='2026-10-11T10:00:00Z', processing_status='PROCESSED',
                         validation_status='VALID', review_required=False)


def catalog(folder, extension='csv'):
    folder.mkdir(parents=True)
    vendor = [['Account', 'Vendor', 'Restricted To'], ['000123', 'Example Vendor', 'North America']]
    contract = [['Contract ID', 'Start Date', 'End Date'], ['000123', '2026-01-01', '2026-12-31']]
    for name, rows in [('vendor_accounts', vendor), ('contracts', contract)]:
        stamp = datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d')
        filename = 'InvoiceMDM' if name == 'vendor_accounts' else 'contract'
        path = folder / f'{filename}_{stamp}.{extension}'
        if extension == 'csv':
            with path.open('w', newline='', encoding='utf-8') as stream:
                csv.writer(stream).writerows(rows)
        else:
            book = Workbook()
            for row in rows:
                book.active.append(row)
            # Exercise actual Excel dates, not just date strings.
            if name == 'contracts':
                book.active['B2'] = datetime(2026, 1, 1)
                book.active['C2'] = datetime(2026, 12, 31)
            book.save(path)
            book.close()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    root = tmp_path / 'internal'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    monkeypatch.setattr(web_app, 'process_document', fake_invoice)
    client = TestClient(web_app.app)
    inputs, output, mdm = tmp_path / 'input', tmp_path / 'output', tmp_path / 'masters'
    inputs.mkdir()
    catalog(mdm)
    payload = dict(invoice_input_folder=str(inputs), output_folder=str(output),
                   master_excel_filename='invoice_master.xlsx', mdm_folder=str(mdm),
                   review_threshold=90, rounding_tolerance=.02, revision='')
    return root, client, payload


@pytest.mark.parametrize('extension', ['csv', 'xlsx'])
def test_save_reload_process_download_and_reset_preserve_history_and_masters(environment, extension):
    root, client, payload = environment
    if extension == 'xlsx':
        folder = Path(payload['mdm_folder'])
        for path in folder.iterdir():
            path.unlink()
        # Fixture-only masters, not real company data.
        folder.rmdir()
        catalog(folder, extension)
    before = {p.name: p.read_bytes() for p in Path(payload['mdm_folder']).iterdir()}
    store = web_app.storage()
    generation = store.generation
    artifact = root / 'models' / 'owned.joblib'
    artifact.parent.mkdir()
    artifact.write_bytes(b'owned-model')
    store.save_batch(uuid4().hex, [fake_invoice(type('D', (), {
        'filename': 'old.pdf', 'source_email': '', 'source_attachment': '',
        'attachment_index': None, 'intake_status': ''})(), .02, 95)])
    response = client.post('/api/settings', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['warnings'] == []
    saved = load_ui_settings(web_app.settings)
    assert saved.review_threshold == 90 and saved.revision
    assert saved.output_folder == str(Path(payload['output_folder']).resolve())
    assert saved.mdm_folder == str(Path(payload['mdm_folder']).resolve())
    assert web_app.storage().generation == generation
    assert web_app.storage().database == root / 'invoice_history.sqlite3'
    assert artifact.read_bytes() == b'owned-model'
    assert client.get('/api/config').json()['minimum_field_confidence'] == 90
    assert client.get('/api/config').json()['cumulative_invoice_report_file'] == str(Path(payload['output_folder']) / 'MDM' / 'Invoice_data.csv')
    run = client.post('/api/process', files=[('files', ('manual.pdf', b'%PDF-test', 'application/pdf'))])
    assert run.status_code == 200, run.text
    row = run.json()['results'][0]['mdm_row']
    assert row['Billing Account'] == ''
    assert row['Vendor -As per MDM'] == 'Example Vendor LLC'
    mdm = client.post('/api/mdm/run', json={
        'batch_id': run.json()['batch_id'], 'generation': generation,
    })
    assert mdm.status_code == 200, mdm.text
    assert mdm.json()['results'][0]['mdm_row']['Billing Account'] == '000123'
    assert mdm.json()['results'][0]['mdm_row']['Vendor -As per MDM'] == 'Example Vendor'
    assert web_app.storage().count() == (2, 2)
    book_response = client.get('/api/download/history/invoice_master.xlsx')
    assert book_response.status_code == 200
    book = load_workbook(io.BytesIO(book_response.content))
    assert book['MDM Invoice Data'].max_row == 3
    book.close()
    assert 'invoice_master.xlsx' in client.get('/api/history').json()['report_files']
    assert before == {p.name: p.read_bytes() for p in Path(payload['mdm_folder']).iterdir()}
    original = Path(payload['invoice_input_folder']) / 'keep.pdf'
    original.write_bytes(b'original')
    prepared = client.post('/api/reset/prepare').json()
    reset = client.post('/api/reset', json={**prepared, 'confirmation': 'CLEAR SAVED INVOICES'})
    assert reset.status_code == 200, reset.text
    assert settings_file(root).is_file() and artifact.read_bytes() == b'owned-model'
    assert original.read_bytes() == b'original'
    book = load_workbook(Path(payload['output_folder']) / 'invoice_master.xlsx')
    assert book['MDM Invoice Data'].max_row == 1
    book.close()
    assert before == {p.name: p.read_bytes() for p in Path(payload['mdm_folder']).iterdir()}


@pytest.mark.parametrize('change', [
    {'output_folder': 'relative'}, {'output_folder': ''},
    {'invoice_input_folder': 'C:/folder-does-not-exist-7b53'},
    {'mdm_folder': 'C:/folder-does-not-exist-7b53'},
    {'master_excel_filename': '../outside.xlsx'}, {'master_excel_filename': 'bad.csv'},
    {'master_excel_filename': 'vendor_accounts.xlsx'}, {'master_excel_filename': 'contracts.xlsx'},
    {'master_excel_filename': 'CON.xlsx'}, {'review_threshold': 0}, {'review_threshold': 101},
    {'processing_database_path': 'unused.sqlite3'},
])
def test_invalid_settings_do_not_replace_good_settings(environment, change):
    root, client, payload = environment
    saved = client.post('/api/settings', json=payload).json()['ui_settings']
    before = settings_file(root).read_bytes()
    response = client.post('/api/settings', json={**saved, **change})
    assert response.status_code == 422, response.text
    assert settings_file(root).read_bytes() == before


def test_changed_output_and_mdm_paths_persist_after_config_reload(environment, tmp_path):
    root, client, payload = environment
    first = client.post('/api/settings', json=payload)
    assert first.status_code == 200, first.text
    saved = first.json()['ui_settings']

    new_output = tmp_path / 'new-output'
    new_mdm = tmp_path / 'new-masters'
    catalog(new_mdm)
    changed = {**saved, 'output_folder': str(new_output), 'mdm_folder': str(new_mdm)}

    response = client.post('/api/settings', json=changed)
    assert response.status_code == 200, response.text
    returned = response.json()['ui_settings']
    assert Path(returned['output_folder']) == new_output.resolve()
    assert Path(returned['mdm_folder']) == new_mdm.resolve()
    assert load_ui_settings(web_app.settings) == UiSettings(**returned)
    config = client.get('/api/config').json()['ui_settings']
    assert config['output_folder'] == str(new_output.resolve())
    assert config['mdm_folder'] == str(new_mdm.resolve())


def test_conflicts_stale_revision_cross_origin_and_active_operation(environment):
    root, client, payload = environment
    assert client.post('/api/settings', json=payload, headers={'Origin': 'https://elsewhere.test'}).status_code == 403
    saved = client.post('/api/settings', json=payload).json()['ui_settings']
    assert client.post('/api/settings', json=payload).status_code == 409
    assert client.post('/api/settings', json={**saved, 'invoice_input_folder': saved['output_folder']}).status_code == 422
    assert client.post('/api/settings', json={**saved, 'invoice_input_folder': saved['mdm_folder']}).status_code == 422
    with folder_operation_lock(root):
        assert client.post('/api/settings', json=saved).status_code == 422


def test_folder_run_pdf_msg_csv_and_unchanged_skipping(environment):
    root, client, payload = environment
    assert client.post('/api/settings', json=payload).status_code == 200
    inputs = Path(payload['invoice_input_folder'])
    (inputs / 'one.pdf').write_bytes(b'%PDF-test')
    (inputs / 'mail.msg').write_bytes(msg_bytes([{'name': 'attachment.pdf', 'data': b'%PDF-attachment'}]))
    (inputs / 'rows.csv').write_text('Invoice,Vendor,Date,Currency,Invoice Amount,Billing Start Date,Billing End Date\nCSV-1,Example Vendor,2026-10-01,USD,15,2026-10-01,2026-10-31\n')
    (inputs / 'ignore.txt').write_text('Not an invoice')
    before = {p.name: p.read_bytes() for p in inputs.iterdir()}
    first = client.post('/api/input-folder/run')
    assert first.status_code == 200, first.text
    assert first.json()['counts']['total'] == 3
    message = next(item for item in first.json()['results'] if item['source_email'])
    assert message['source_email'] == 'mail.msg' and message['source_attachment']
    second = client.post('/api/input-folder/run').json()
    assert second['batch_id'] is None and second['already_processed'] == 3
    assert second['ignored_files'] == 1 and web_app.storage().count() == (1, 3)
    (inputs / 'new.pdf').write_bytes(b'%PDF-new')
    third = client.post('/api/input-folder/run').json()
    assert third['counts']['total'] == 1 and third['already_processed'] == 3
    assert web_app.storage().count() == (2, 4)
    assert all((inputs / name).read_bytes() == data for name, data in before.items())


def test_folder_missing_master_no_fallback_and_bad_workbook(environment):
    root, client, payload = environment
    assert client.post('/api/input-folder/run').status_code == 422
    missing = next(Path(payload['mdm_folder']).glob('contract_*.csv'))
    original = missing.read_bytes()
    missing.unlink()
    response = client.post('/api/settings', json=payload)
    assert response.status_code == 422 and 'contracts' in response.text.casefold()
    missing.write_bytes(original)
    assert client.post('/api/settings', json=payload).status_code == 200
    default = root / 'MDM'
    catalog(default)
    vendor = next(Path(payload['mdm_folder']).glob('InvoiceMDM_*.csv'))
    vendor.unlink()
    assert web_app.storage().vendor_accounts() == []  # No unintended alternate catalog.
    bad = vendor.with_suffix('.xlsx')
    bad.write_bytes(b'not xlsx')
    current = client.get('/api/config').json()['ui_settings']
    assert client.post('/api/settings', json=current).status_code == 422


def test_duplicate_csv_and_xlsx_masters_are_not_arbitrarily_chosen(environment):
    _, client, payload = environment
    assert client.post('/api/settings', json=payload).status_code == 200
    folder = Path(payload['mdm_folder'])
    next(folder.glob('InvoiceMDM_*.csv')).with_suffix('.xlsx').write_bytes(b'other copy')
    with pytest.raises(ValueError, match='multiple current Vendor Accounts'):
        catalog_paths(folder)
    response = client.get('/api/config')
    assert response.status_code == 200 and response.json()['storage_ready']
    assert any('multiple current Vendor Accounts' in warning for warning in response.json()['warnings'])


def test_dated_vendor_export_uses_only_todays_file(tmp_path):
    old = tmp_path / '47711_InvoiceMDM_20261030T10_59_26_20261030_105926Z.csv'
    current = tmp_path / '47711_InvoiceMDM_20261031T10_59_26_20261031_105926Z.xlsx'
    contracts = tmp_path / 'contracts.csv'
    old.write_text('old', encoding='utf-8')
    current.write_bytes(b'current')
    contracts.write_text('contracts', encoding='utf-8')

    assert catalog_paths(tmp_path, date(2026, 10, 31)) == (current, contracts)


def test_dated_vendor_export_does_not_require_a_fixed_prefix(tmp_path):
    current = tmp_path / 'arbitrary_prefix_InvoiceMDM_20261031_final_120000.csv'
    contracts = tmp_path / 'contracts.xlsx'
    current.write_text('current', encoding='utf-8')
    contracts.write_bytes(b'contracts')

    assert catalog_paths(tmp_path, date(2026, 10, 31)) == (current, contracts)


def test_vendor_date_must_immediately_follow_invoicemdm_keyword(tmp_path):
    malformed = tmp_path / 'arbitrary_prefix_InvoiceMDM_final_20261031.csv'
    malformed.write_text('wrong', encoding='utf-8')

    with pytest.raises(ValueError, match='dated today'):
        catalog_paths(tmp_path, date(2026, 10, 31), allow_legacy=False)


def test_unrelated_dated_file_is_not_a_vendor_master(tmp_path):
    unrelated = tmp_path / 'other_report_20261031.csv'
    legacy = tmp_path / 'vendor_accounts.csv'
    unrelated.write_text('not mdm', encoding='utf-8')
    legacy.write_text('legacy', encoding='utf-8')

    assert catalog_paths(tmp_path, date(2026, 10, 31))[0] == legacy


def test_dated_contract_export_uses_only_todays_file(tmp_path):
    vendor = tmp_path / 'InvoiceMDM_20261031.csv'
    old = tmp_path / 'any_contract_20261030_export.csv'
    current = tmp_path / 'any_contract_20261031_anything.xlsx'
    vendor.write_text('vendor', encoding='utf-8')
    old.write_text('old', encoding='utf-8')
    current.write_bytes(b'current')

    assert catalog_paths(tmp_path, date(2026, 10, 31)) == (vendor, current)


def test_contract_date_must_immediately_follow_contract_keyword(tmp_path):
    vendor = tmp_path / 'InvoiceMDM_20261031.csv'
    malformed = tmp_path / 'any_contract_final_20261031.csv'
    vendor.write_text('vendor', encoding='utf-8')
    malformed.write_text('wrong', encoding='utf-8')

    with pytest.raises(ValueError, match='Contracts export dated today'):
        catalog_paths(tmp_path, date(2026, 10, 31), allow_legacy=False)


def test_misspelled_contract_keyword_is_not_selected(tmp_path):
    vendor = tmp_path / 'InvoiceMDM_20261031.csv'
    misspelled = tmp_path / 'any_contracst_20261031.csv'
    legacy = tmp_path / 'contracts.csv'
    vendor.write_text('vendor', encoding='utf-8')
    misspelled.write_text('wrong', encoding='utf-8')
    legacy.write_text('legacy', encoding='utf-8')

    assert catalog_paths(tmp_path, date(2026, 10, 31)) == (vendor, legacy)


def test_dated_contract_export_requires_today_and_rejects_duplicates(tmp_path):
    vendor = tmp_path / 'InvoiceMDM_20261031.csv'
    vendor.write_text('vendor', encoding='utf-8')
    (tmp_path / 'contract_20261030.csv').write_text('old', encoding='utf-8')
    with pytest.raises(ValueError, match='no Contracts export dated today'):
        catalog_paths(tmp_path, date(2026, 10, 31))

    for suffix in ('csv', 'xlsx'):
        (tmp_path / f'contract_20261031.{suffix}').write_bytes(b'current')
    with pytest.raises(ValueError, match='multiple current Contracts'):
        catalog_paths(tmp_path, date(2026, 10, 31))


def test_dated_vendor_export_requires_today_and_rejects_duplicates(tmp_path):
    old = tmp_path / '47711_InvoiceMDM_20261030T10_59_26_20261030_105926Z.csv'
    old.write_text('old', encoding='utf-8')
    with pytest.raises(ValueError, match='no Vendor Accounts export dated today'):
        catalog_paths(tmp_path, date(2026, 10, 31))

    for suffix in ('csv', 'xlsx'):
        (tmp_path / f'47711_InvoiceMDM_20261031T10_59_26_20261031_105926Z.{suffix}').write_bytes(b'current')
    with pytest.raises(ValueError, match='multiple current Vendor Accounts'):
        catalog_paths(tmp_path, date(2026, 10, 31))


def test_saved_threshold_is_used_when_manual_api_omits_it(environment, monkeypatch):
    _, client, payload = environment
    assert client.post('/api/settings', json=payload).status_code == 200
    thresholds = []
    def capture(document, tolerance, threshold):
        thresholds.append(threshold)
        return fake_invoice(document, tolerance, threshold)
    monkeypatch.setattr(web_app, 'process_document', capture)
    response = client.post('/api/process', files=[('files', ('test.pdf', b'%PDF', 'application/pdf'))])
    assert response.status_code == 200 and thresholds == [90]


def test_scheduled_outlook_uses_saved_locations_and_threshold(environment, monkeypatch):
    root, client, payload = environment
    assert client.post('/api/settings', json=payload).status_code == 200
    from services import outlook_scheduler
    from services.outlook_folder import FolderRun
    monkeypatch.setattr(outlook_scheduler, 'settings', web_app.settings)
    seen = []
    def run(store, tolerance, threshold, max_bytes, **options):
        seen.append((store.output_folder, store.vendor_catalog_folder(), store.excel_filename, threshold))
        return FolderRun(store.outlook_folder, None, 0, 0, 0, [], [])
    monkeypatch.setattr(outlook_scheduler, 'run_outlook_folder', run)
    assert outlook_scheduler.main() == 0
    assert seen == [(Path(payload['output_folder']), Path(payload['mdm_folder']), 'invoice_master.xlsx', 90)]
