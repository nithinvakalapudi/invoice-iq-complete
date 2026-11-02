import csv
import io
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import web_app
from models.invoice_schema import Invoice, InvoiceResult
from services.local_storage import LocalStorage
from services.invoice_folder import save_upload_batch
from services.mdm_csv_service import REPORT_NAME, generate_mdm_csv, mdm_row
from services.vendor_matching import (
    VendorAccount, _longest_contiguous, _ordered_overlap,
    load_vendor_accounts, match_vendor_account, resolve_vendor_account, vendor_similarity,
)


def accounts():
    return [
        VendorAccount('CON-001', 'Blue Ocean Technologies LLC', 'APAC'),
        VendorAccount('CON-002', 'Blue Ocean Technologies LLC', 'EMEA'),
        VendorAccount('CON-003', 'Blue Ocean Technologies LLC', 'Americas'),
    ]


def test_full_and_suffix_removed_names_outrank_partial_sequences():
    assert vendor_similarity('Blue Ocean Technologies LLC', 'Blue Ocean Technologies LLC') == 100
    assert vendor_similarity('Blue Ocean Technologies', 'Blue Ocean Technologies LLC') == 99
    assert vendor_similarity('Blue Ocean Technologies', 'Blue Ocean') > vendor_similarity(
        'Blue Ocean Technologies', 'Blue')


@pytest.mark.parametrize('name', [
    'ABC Global Technology Solutions Limited',
    'ABC Global Technology And Consulting Services',
    'One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve',
])
def test_sequences_scale_to_all_words_without_fixed_maximum(name):
    tokens = tuple(name.casefold().split())
    assert _longest_contiguous(tokens, tokens) == len(tokens)
    assert _ordered_overlap(tokens, tokens) == len(tokens)
    assert vendor_similarity(name, name) == 100
    assert vendor_similarity(name, name + ' LLC') == 99


def test_noncontiguous_ordered_words_help_but_are_weaker_than_full_name():
    assert _ordered_overlap(('blue', 'ocean', 'technologies'), ('blue', 'technologies')) == 2
    assert _longest_contiguous(('blue', 'ocean', 'technologies'), ('blue', 'technologies')) == 1
    assert vendor_similarity('Blue Ocean Technologies', 'Blue Technologies') > 0
    assert vendor_similarity('Blue Ocean Technologies', 'Blue Ocean Technologies LLC') > vendor_similarity(
        'Blue Ocean Technologies', 'Blue Technologies')


def test_region_selects_correct_account_over_otherwise_same_vendor():
    assert match_vendor_account('BLUE OCEAN TECHNOLOGIES', 'EMEA', accounts()).account.account == 'CON-002'
    assert match_vendor_account('BLUE OCEAN TECHNOLOGIES', 'West Palm Beach, FL', accounts()).account.account == 'CON-003'
    assert match_vendor_account('BLUE OCEAN TECHNOLOGIES', 'Hong Kong', accounts()).account.account == 'CON-001'
    assert match_vendor_account('BLUE OCEAN TECHNOLOGIES', None, accounts()) is None


def test_short_mdm_name_uses_explicit_alias_and_region(tmp_path):
    catalog = tmp_path / 'vendor_accounts.csv'
    catalog.write_text('Account,Vendor,Restricted To,Vendor Alias\n'
                       'CON-2026-0001,Blue Ocean,APAC,Blue Ocean Technologies LLC\n'
                       'CON-2026-0021,Blue Ocean Technologies LLC,EMEA,\n', encoding='utf-8')
    loaded = load_vendor_accounts(catalog)
    matched = resolve_vendor_account('Blue Ocean Technologies, LLC', 'Singapore', loaded)
    assert matched.status == 'MATCHED'
    assert matched.match.account.account == 'CON-2026-0001'
    assert resolve_vendor_account('Blue Ocean Technologies, LLC', None, loaded).status == 'LOW_CONFIDENCE'


def test_unique_vendor_matches_without_region_check_but_ambiguous_vendor_does_not():
    assert match_vendor_account('Blue Ocean Technologies', 'EMEA', accounts()[:1]).account.account == 'CON-001'
    assert match_vendor_account('Blue Ocean Technologies', None, accounts()[:1]).account.account == 'CON-001'
    duplicates = [VendorAccount('A', 'Blue Ocean Technologies', 'EMEA'),
                  VendorAccount('B', 'Blue Ocean Technologies LLC', 'EMEA')]
    assert match_vendor_account('Blue Ocean Technologies', 'EMEA', duplicates).account.account == 'A'
    assert match_vendor_account('Blue Ocean Technologies', 'unknown', accounts()) is None


def test_best_vendor_name_takes_priority_over_region_of_weaker_vendor():
    entries = [VendorAccount('wrong', 'Blue Ocean Technologies LLC', 'APAC'),
               VendorAccount('right', 'Blue Ocean Technology LLC', 'EMEA')]
    assert match_vendor_account('Blue Ocean Technologies', 'EMEA', entries).account.account == 'wrong'


def test_printed_contract_id_does_not_override_ambiguous_vendor_and_region():
    entries = [VendorAccount('CON-2026-0001', 'Blue Ocean Technologies LLC', 'APAC'),
               VendorAccount('CON-2026-0021', 'Blue Ocean Technologies LLC', 'APAC')]
    assert match_vendor_account('Blue Ocean Technologies', 'APAC', entries) is None
    assert match_vendor_account('Blue Ocean Technologies', 'APAC', entries,
                                contract_id='CON-2026-0021') is None
    assert match_vendor_account('Blue Ocean Technologies', 'EMEA', entries,
                                contract_id='CON-2026-0021') is None
    assert match_vendor_account('Other Company', 'APAC', entries,
                                contract_id='CON-2026-0021') is None


def test_local_catalog_populates_cumulative_mdm_without_changing_extracted_vendor(tmp_path):
    store = LocalStorage(tmp_path / 'local_data')
    catalog = store.root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor,Restricted To\nCON-001,Blue Ocean Technologies LLC,APAC\n'
                       'CON-002,Blue Ocean Technologies LLC,EMEA\n', encoding='utf-8')
    result = InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean Technologies', region='EMEA',
                                          invoice_number='INV-1'))
    store.save_batch(uuid4().hex, [result])
    with (store.root / REPORT_NAME).open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []
    assert result.invoice.vendor_name == 'Blue Ocean Technologies'
    assert mdm_row(result)['Billing Account'] == ''
    assert next(csv.DictReader(io.StringIO(generate_mdm_csv([result], store.vendor_accounts()).decode('utf-8-sig'))))['Billing Account'] == 'CON-002'


def test_catalog_rejects_missing_columns_and_preserves_leading_zeroes(tmp_path):
    path = tmp_path / 'accounts.csv'
    path.write_text('Account,Vendor\n00123,Blue Ocean\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Restricted To'):
        load_vendor_accounts(path)
    path.write_text('Account,Vendor,Restricted To\n00123,Blue Ocean,EMEA\n', encoding='utf-8')
    assert load_vendor_accounts(path)[0].account == '00123'


def test_catalog_reads_account_number_as_billing_account(tmp_path):
    path = tmp_path / 'InvoiceMDM_20261031.csv'
    path.write_text('Account Number,Vendor,Restricted To\n00123,Blue Ocean,EMEA\n',
                    encoding='utf-8')

    assert load_vendor_accounts(path)[0].account == '00123'


def test_invalid_catalog_warns_but_does_not_block_invoice_history(tmp_path):
    store = LocalStorage(tmp_path / 'local_data')
    catalog = store.root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor\n00123,Blue Ocean\n', encoding='utf-8')
    result = InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean', region='EMEA',
                                          invoice_number='INV-2'))
    warnings = store.save_batch(uuid4().hex, [result])
    assert any('vendor_accounts.csv' in warning for warning in warnings)
    with (store.root / REPORT_NAME).open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []
    assert store.count() == (1, 1)


def test_api_result_and_batch_download_use_the_same_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(tmp_path)))
    store = LocalStorage(tmp_path)
    catalog = store.root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor,Restricted To\nEMEA-001,Blue Ocean Technologies LLC,EMEA\n',
                       encoding='utf-8')
    batch_id = uuid4().hex
    store.save_batch(batch_id, [InvoiceResult(invoice=Invoice(
        vendor_name='Blue Ocean Technologies', region='EMEA', invoice_number='INV-3'))])
    client = TestClient(web_app.app)
    payload = client.get(f'/api/batches/{batch_id}').json()['results'][0]
    assert payload['mdm_row']['Billing Account'] == 'EMEA-001'
    assert payload['mdm_row']['Vendor -As per MDM'] == 'Blue Ocean Technologies LLC'
    assert payload['invoice']['vendor_name'] == 'Blue Ocean Technologies'
    content = client.get(f'/api/download/batch/{batch_id}/{REPORT_NAME}').content
    assert list(csv.DictReader(io.StringIO(content.decode('utf-8-sig')))) == []


def test_run_mdm_rechecks_master_and_updates_saved_csv_excel_without_reextracting(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    store = LocalStorage(root)
    catalog = root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor,Restricted To\nOLD-01,Blue Ocean Technologies LLC,APAC\n',
                       encoding='utf-8')
    original = Invoice(vendor_name='Blue Ocean Technologies, LLC', invoice_number='BOT-1001')
    batch_id = uuid4().hex
    store.save_batch(batch_id, [InvoiceResult(invoice=original, source_file='invoice.pdf')])
    catalog.write_text('Account,Vendor,Restricted To\nNEW-02,Blue Ocean Technologies LLC,EMEA\n',
                       encoding='utf-8')
    master_before = catalog.read_bytes()
    client = TestClient(web_app.app)
    response = client.post('/api/mdm/run', headers={'Origin': 'http://testserver'}, json={
        'batch_id': batch_id, 'generation': store.generation,
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['mdm_summary'] == {'matched': 1, 'low_confidence': 0, 'not_found': 0, 'contracts_present': 0, 'contracts_missing_or_invalid': 0}
    assert payload['results'][0]['mdm_row']['Billing Account'] == 'NEW-02'
    assert payload['results'][0]['mdm_row']['Vendor -As per MDM'] == 'Blue Ocean Technologies LLC'
    assert payload['results'][0]['invoice'] == original.to_dict()
    with (root / REPORT_NAME).open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []
    workbook = load_workbook(io.BytesIO((root / 'Invoice_History.xlsx').read_bytes()), read_only=True)
    assert workbook['MDM Invoice Data'].max_row == 1
    workbook.close()
    assert store.count() == (1, 1)
    assert catalog.read_bytes() == master_before


def test_run_mdm_reports_ambiguous_and_rejects_missing_catalog(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    monkeypatch.setattr(LocalStorage, 'vendor_catalog_folder', lambda self: root / 'MDM')
    store = LocalStorage(root)
    batch_id = uuid4().hex
    store.save_batch(batch_id, [InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean Technologies',
                                service_start_date='2026-10-01', service_end_date='2026-10-31'))])
    client = TestClient(web_app.app)
    request = {'batch_id': batch_id, 'generation': store.generation}
    headers = {'Origin': 'http://testserver'}
    assert client.post('/api/mdm/run', headers=headers, json=request).status_code == 422
    catalog = root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor,Restricted To\nA,Blue Ocean Technologies LLC,APAC\n'
                       'B,Blue Ocean Technologies LLC,EMEA\n', encoding='utf-8')
    response = client.post('/api/mdm/run', headers=headers, json=request)
    assert response.status_code == 200, response.text
    assert response.json()['mdm_summary'] == {'matched': 0, 'low_confidence': 1, 'not_found': 0, 'contracts_present': 0, 'contracts_missing_or_invalid': 0}
    assert response.json()['results'][0]['mdm_row']['Billing Account'] == ''
    assert response.json()['counts']['review'] == 1
    assert 'no invoice or email Region' in response.json()['results'][0]['mdm_row']['Review reasons']


def test_human_region_correction_resolves_email_conflict(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    store = LocalStorage(root)
    catalog = root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor,Restricted To\nAPAC-01,Blue Ocean Technologies LLC,APAC\n'
                       'EMEA-02,Blue Ocean Technologies LLC,EMEA\n', encoding='utf-8')
    result = InvoiceResult(invoice=Invoice(
        vendor_name='Blue Ocean Technologies LLC', invoice_number='INV-1',
        invoice_date='2026-10-01', currency='USD', total_amount='100.00',
        service_start_date='2026-10-01', service_end_date='2026-10-31',
        region='Singapore'), processing_status='PROCESSED',
        region_match_issue="Invoice Region 'Singapore' conflicts with email Region 'EMEA'")
    batch_id = uuid4().hex
    store.save_batch(batch_id, [result])
    client = TestClient(web_app.app)
    before = client.get(f'/api/batches/{batch_id}').json()['results'][0]['mdm_row']
    assert before['Billing Account'] == ''
    changed = client.post(f'/api/batches/{batch_id}/review', json={
        'generation': store.generation, 'index': 0, 'fields': {'region': 'EMEA'},
        'tolerance': 0.02, 'threshold': 95,
    })
    assert changed.status_code == 200, changed.text
    after = changed.json()['results'][0]['mdm_row']
    assert after['Billing Account'] == 'EMEA-02'
    assert after['Review status'] == 'SUCCESS'


def test_vendor_accounts_remains_authoritative_when_contracts_disagree(tmp_path):
    vendors = tmp_path / 'vendor_accounts.csv'
    contracts = tmp_path / 'contracts.csv'
    vendors.write_text('Account,Vendor,Restricted To\nGOOD-01,Blue Ocean Technologies LLC,EMEA\n'
                       'BAD-02,Other Vendor LLC,EMEA\n', encoding='utf-8')
    contracts.write_text('Contract ID,Vendor\nGOOD-01,Blue Ocean Technologies LLC\n'
                         'BAD-02,Different Company LLC\n', encoding='utf-8')
    loaded = load_vendor_accounts(vendors, contracts)
    assert [entry.account for entry in loaded] == ['GOOD-01', 'BAD-02']
    assert match_vendor_account('Other Vendor', 'EMEA', loaded).account.account == 'BAD-02'


def test_contract_dates_checked_after_billing_account_match_without_changing_invoice(tmp_path):
    vendors = tmp_path / 'vendor_accounts.csv'
    contracts = tmp_path / 'contracts.csv'
    vendors.write_text('Account,Vendor,Restricted To\nCON-01,Blue Ocean,APAC\n', encoding='utf-8')
    contracts.write_text('Contract ID,Vendor,Start Date,End Date\n'
                         'CON-01,Blue Ocean Technologies LLC,2025-01-01,2030-12-31\n', encoding='utf-8')
    vendor_original, contract_original = vendors.read_bytes(), contracts.read_bytes()
    accounts = load_vendor_accounts(vendors, contracts)
    invoice = Invoice(vendor_name='Blue Ocean', region='APAC', invoice_number='BOT-1',
                      service_start_date='2026-10-01', service_end_date='2026-10-31')
    original = invoice.to_dict().copy()
    row = mdm_row(InvoiceResult(invoice=invoice), accounts)
    assert row['Billing Account'] == 'CON-01'
    assert row['Contract check status'] == 'PRESENT'
    assert row['Comments'] == ''
    assert row['Contract Start Date'] == '2025-01-01'
    assert row['Contract End Date'] == '2030-12-31'
    assert row['Contract check reason'] == ''
    assert invoice.to_dict() == original
    assert vendors.read_bytes() == vendor_original
    assert contracts.read_bytes() == contract_original


def test_missing_or_ambiguous_contract_dates_request_review(tmp_path):
    vendors = tmp_path / 'vendor_accounts.csv'
    contracts = tmp_path / 'contracts.csv'
    vendors.write_text('Account,Vendor,Restricted To\nCON-01,Blue Ocean,APAC\n', encoding='utf-8')
    result = InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean', region='APAC', invoice_number='BOT-1',
                           service_start_date='2026-10-01', service_end_date='2026-10-31'))

    contracts.write_text('Contract ID,Start Date,End Date\nOTHER,2025-01-01,2025-12-31\n', encoding='utf-8')
    row = mdm_row(result, load_vendor_accounts(vendors, contracts))
    assert row['Billing Account'] == 'CON-01'
    assert row['Contract check status'] == 'NOT_FOUND'
    assert 'Contract:' in row['Review reasons']
    assert row['Comments'] == 'Contract is not valid'

    contracts.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,\n', encoding='utf-8')
    row = mdm_row(result, load_vendor_accounts(vendors, contracts))
    assert row['Contract check status'] == 'MISSING_DATES'
    assert row['Review status'] == 'REVIEW_REQUIRED'
    assert row['Comments'] == 'Contract is not valid'

    contracts.write_text('Contract ID,Start Date,End Date\nCON-01,2025-12-31,2025-01-01\n',
                         encoding='utf-8')
    row = mdm_row(InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean', region='APAC',
                                           service_start_date='2026-10-01', service_end_date='2026-10-31',
                                           invoice_number='BOT-1', invoice_comments='Printed note')),
                  load_vendor_accounts(vendors, contracts))
    assert row['Contract check status'] == 'INVALID_DATES'
    assert row['Comments'] == 'Printed note; Contract is not valid'

    contracts.write_text('Contract ID,Start Date,End Date\n'
                         'CON-01,2025-01-01,2025-12-31\nCON-01,2025-01-01,2025-12-31\n', encoding='utf-8')
    row = mdm_row(result, load_vendor_accounts(vendors, contracts))
    assert row['Contract check status'] == 'AMBIGUOUS'
    assert row['Billing Account'] == 'CON-01'
    assert row['Comments'] == ''


def test_ended_contract_is_rejected_and_excluded_from_approved_excel(tmp_path):
    vendors = tmp_path / 'vendor_accounts.csv'
    contracts = tmp_path / 'contracts.csv'
    vendors.write_text('Account,Vendor,Restricted To\nCON-01,Blue Ocean,APAC\n', encoding='utf-8')
    contracts.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,2025-12-31\n',
                         encoding='utf-8')
    result = InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean', region='APAC',
                                           invoice_number='BOT-1', service_start_date='2026-10-01',
                                           service_end_date='2026-10-31'))
    row = mdm_row(result, load_vendor_accounts(vendors, contracts))
    assert row['Billing Account'] == 'CON-01'
    assert row['Contract check status'] == 'EXPIRED'
    assert row['Contract check reason'] == 'Contract CON-01 expired on 2025-12-31'
    assert row['Contract End Date'] == '2025-12-31'
    assert row['Review status'] == 'REJECTED'
    assert row['Comments'] == 'Contract expired'
    assert 'expired' in row['Review reasons'].lower()
    assert web_app._mdm_summary([row])['contracts_missing_or_invalid'] == 1


def test_run_mdm_refreshes_contract_check_without_changing_the_mdm_csv(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    store = LocalStorage(root)
    catalog = root / 'MDM'
    catalog.mkdir(exist_ok=True)
    (catalog / 'vendor_accounts.csv').write_text(
        'Account,Vendor,Restricted To\nCON-01,Blue Ocean Technologies LLC,APAC\n', encoding='utf-8')
    contract_file = catalog / 'contracts.csv'
    contract_file.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,\n', encoding='utf-8')
    batch_id = uuid4().hex
    store.save_batch(batch_id, [InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean Technologies LLC',
                                                        service_start_date='2026-10-01', service_end_date='2026-10-31',
                                                            region='APAC', invoice_number='BOT-1',
                                                            invoice_date='2026-10-01', currency='USD',
                                                            subtotal='100.00', tax_amount='0.00', total_amount='100.00'))])
    client = TestClient(web_app.app)
    payload = {'batch_id': batch_id, 'generation': store.generation}
    headers = {'Origin': 'http://testserver'}
    first = client.post('/api/mdm/run', json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json()['results'][0]['mdm_row']['Contract check status'] == 'MISSING_DATES'
    assert first.json()['mdm_summary']['contracts_missing_or_invalid'] == 1
    assert first.json()['results'][0]['mdm_row']['Review status'] == 'REVIEW_REQUIRED'
    assert first.json()['results'][0]['mdm_row']['Comments'] == 'Contract is not valid'
    with (root / REPORT_NAME).open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []
    contract_file.write_text('Contract ID,Start Date,End Date\nCON-01,2025-01-01,2030-12-31\n',
                             encoding='utf-8')
    second = client.post('/api/mdm/run', json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()['results'][0]['mdm_row']['Contract check status'] == 'PRESENT'
    assert second.json()['mdm_summary']['contracts_present'] == 1
    assert second.json()['results'][0]['mdm_row']['Comments'] == ''
    with (root / REPORT_NAME).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        assert 'Contract check status' not in reader.fieldnames
        assert list(reader) == []  # A current contract alone does not approve an incomplete invoice.


def test_mdm_is_explicit_stage_and_check_requires_run(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    store = LocalStorage(root)
    catalog = root / 'MDM'
    catalog.mkdir(exist_ok=True)
    (catalog / 'vendor_accounts.csv').write_text(
        'Account,Vendor,Restricted To\nCON-01,Blue Ocean Technologies LLC,APAC\n', encoding='utf-8')
    (catalog / 'contracts.csv').write_text(
            'Contract ID,Start Date,End Date\nCON-01,2025-01-01,2030-12-31\n', encoding='utf-8')
    batch_id, results, _ = save_upload_batch(
        store, [('demo.csv', b'input')], 0.02, 95, 100000,
        lambda *args: None,
        lambda *args: [InvoiceResult(invoice=Invoice(
            vendor_name='Blue Ocean Technologies LLC', invoice_number='BOT-1', region='APAC'))],
    )
    assert results[0].mdm_checked is False
    client = TestClient(web_app.app)
    request = {'batch_id': batch_id, 'generation': store.generation}
    headers = {'Origin': 'http://testserver'}
    before = client.get(f'/api/batches/{batch_id}').json()['results'][0]
    assert before['mdm_row']['Billing Account'] == ''
    assert before['mdm_row']['Contract check status'] == ''
    with (root / REPORT_NAME).open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []
    assert client.post('/api/mdm/check', json=request, headers=headers).status_code == 409
    run = client.post('/api/mdm/run', json=request, headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()['results'][0]['mdm_row']['Billing Account'] == 'CON-01'
    assert run.json()['results'][0]['mdm_row']['Contract Start Date'] == '2025-01-01'
    assert client.get(f'/api/batches/{batch_id}').json()['results'][0]['mdm_checked'] is True
    check = client.post('/api/mdm/check', json=request, headers=headers)
    assert check.status_code == 200, check.text
    assert check.json()['mdm_summary']['matched'] == 1
    assert check.json()['mdm_summary']['contracts_present'] == 1


def test_invoice_number_is_never_used_and_other_invoice_fields_remain_unchanged():
    master = [VendorAccount('CON-2026-0001', 'Blue Ocean Technologies LLC', 'APAC')]
    invoice = Invoice(vendor_name='Blue Ocean Technologies, LLC', region='APAC',
                      invoice_number='BOT-2026-1001', invoice_date='10/01/2026',
                      currency='USD', subtotal='4500.00', tax_amount='0.00')
    before = invoice.to_dict().copy()
    row = mdm_row(InvoiceResult(invoice=invoice), master)
    assert row['Billing Account'] == 'CON-2026-0001'
    assert row['Billing Account match status'] == 'MATCHED'
    assert row['Invoice Number'] == 'BOT-2026-1001'
    assert row['Vendor -As per MDM'] == 'Blue Ocean Technologies LLC'
    assert invoice.to_dict() == before


@pytest.mark.parametrize('extracted,canonical,aliases', [
    ('Blue Ocean Technologies, LLC', 'Blue Ocean Technologies LLC', ()),
    ('BLUE OCEAN TECHNOLOGIES', 'Blue Ocean Technologies, Ltd.', ()),
    ('Blue Ocean Technologies, LLC', 'Blue Ocean', ('Blue Ocean Technologies LLC',)),
    ('Blue Ocean Technologies, LLC', 'Blue ocean', ()),
    ('Blur OCean Technologies LLC', 'Blue ocean', ()),
])
def test_mdm_vendor_uses_matched_master_name_including_aliases(extracted, canonical, aliases):
    master = [VendorAccount('00123', canonical, 'APAC', aliases=aliases)]
    result = InvoiceResult(invoice=Invoice(vendor_name=extracted, region='Singapore',
                                          invoice_number='INV-1'))
    original = result.invoice.to_dict().copy()
    row = mdm_row(result, master)
    assert row['Vendor -As per MDM'] == canonical
    assert row['Billing Account'] == '00123'
    assert row['Billing Account match status'] == 'MATCHED'
    assert result.invoice.to_dict() == original


@pytest.mark.parametrize('invoice_vendor', ['Blue Ocean Technologies LLC', 'Blur OCean Technologies LLC'])
def test_short_master_vendor_name_uses_region_and_preserves_selected_master_spelling(invoice_vendor):
    master = [VendorAccount('APAC-01', 'Blue ocean', 'APAC'),
              VendorAccount('EMEA-02', 'BLUE OCEAN', 'EMEA')]
    result = InvoiceResult(invoice=Invoice(vendor_name=invoice_vendor, region='Singapore'))
    original = result.invoice.to_dict().copy()
    row = mdm_row(result, master)
    assert row['Vendor -As per MDM'] == 'Blue ocean'
    assert row['Billing Account'] == 'APAC-01'
    assert row['Billing Account match status'] == 'MATCHED'
    assert result.invoice.to_dict() == original
    result.invoice.region = 'EMEA'
    assert mdm_row(result, master)['Vendor -As per MDM'] == 'BLUE OCEAN'


@pytest.mark.parametrize('region', [None, 'unknown'])
def test_short_mdm_names_with_multiple_accounts_still_require_unambiguous_region(region):
    master = [VendorAccount('APAC-01', 'Blue ocean', 'APAC'),
              VendorAccount('EMEA-02', 'Blue ocean', 'EMEA')]
    resolution = resolve_vendor_account('Blur Ocean Technologies LLC', region, master)
    assert resolution.status == 'LOW_CONFIDENCE'
    assert resolution.match is None


def test_short_mdm_names_with_multiple_accounts_in_same_region_are_not_guessed():
    master = [VendorAccount('APAC-01', 'Blue ocean', 'APAC'),
              VendorAccount('APAC-02', 'BLUE OCEAN', 'APAC')]
    result = InvoiceResult(invoice=Invoice(vendor_name='Blur Ocean Technologies LLC', region='APAC'))
    row = mdm_row(result, master)
    assert row['Billing Account match status'] == 'LOW_CONFIDENCE'
    assert row['Billing Account'] == ''
    assert row['Vendor -As per MDM'] == 'Blur Ocean Technologies LLC'


@pytest.mark.parametrize('full_vendor,short_vendor,ocr_vendor', [
    ('Blue Ocean Technologies LLC', 'Blue Ocean', 'Blur Ocean Technologies LLC'),
    ('Acme Global Solutions Ltd', 'Acme Global', 'Acme GlobaI Solutions Ltd'),
    ('Orion Market Data Services Inc', 'Orion Market Data', 'Orion Marlet Data Services Inc'),
    ('Summit Financial Analytics GmbH', 'Summit Financial', 'Summit Financiel Analytics GmbH'),
    ('Vertex Digital Production Pvt. Ltd.', 'Vertex Digital', 'Vertey Digital Production Pvt. Ltd.'),
    ('Data Labs Automation Corp', 'Data Labs', 'Date Labs Automation Corp'),
    ('Café Horizon Data SA', 'Café Horizon', 'Café Horixon Data SA'),
    ('Alpha Beta Cloud Computing Market Data Europe Corp',
     'Alpha Beta Cloud Computing Market Data', 'Alpha Beta Clovd Computing Market Data Europe Corp'),
])
def test_short_name_and_ocr_matching_remain_weaker_than_full_or_exact_names(full_vendor, short_vendor, ocr_vendor):
    """Vendor strings are test fixtures, never rules in the production matcher."""
    assert vendor_similarity(ocr_vendor, full_vendor) > vendor_similarity(ocr_vendor, short_vendor)
    assert vendor_similarity(full_vendor, full_vendor) > vendor_similarity(full_vendor, short_vendor)
    assert vendor_similarity(ocr_vendor, short_vendor) >= 70


@pytest.mark.parametrize('invoice,master', [
    ('Blue Ocean Technologies LLC', 'Blue'),
    ('Red Ocean Technologies LLC', 'Blue Ocean'),
    ('Ocean Blue Technologies LLC', 'Blue Ocean'),
    ('Blue Services Technologies LLC', 'Blue Services'),
    ('Acme Global Solutions Ltd', 'Acme'),
    ('Acme Global Solutions Ltd', 'Different Global'),
    ('Summit Financial Analytics GmbH', 'Unrelated Financial'),
    ('Vertex Services Production Pvt. Ltd.', 'Vertex Services'),
])
def test_weak_vendor_evidence_does_not_force_a_match(invoice, master):
    assert vendor_similarity(invoice, master) < 70
    assert resolve_vendor_account(invoice, 'APAC', [VendorAccount('00123', master, 'APAC')]).match is None


@pytest.mark.parametrize('word_count', [2, 3, 4, 7, 16, 32])
@pytest.mark.parametrize('ocr_error', [False, True])
def test_generated_vendor_names_of_any_length_resolve_region_and_exact_output_name(word_count, ocr_error):
    """Exercise generated brands, not a fixed list of recognized companies."""
    brand = ' '.join(f'Brand{number}' for number in range(word_count))
    extracted = f'{brand} Licensing Platforms Pvt. Ltd.'
    if ocr_error:
        extracted = extracted.replace('Brand0', 'Brqnd0', 1)
    master = [VendorAccount('000123', brand, 'APAC'),
              VendorAccount('000456', brand.upper(), 'EMEA'),
              VendorAccount('009999', 'Unrelated Supplier LLC', 'APAC')]
    result = InvoiceResult(invoice=Invoice(vendor_name=extracted, region='Singapore', invoice_number='TEST-1'))
    before = result.invoice.to_dict().copy()
    row = mdm_row(result, master)
    assert row['Billing Account match status'] == 'MATCHED'
    assert row['Billing Account'] == '000123'
    assert row['Vendor -As per MDM'] == brand
    assert result.invoice.to_dict() == before
    unresolved = resolve_vendor_account(extracted, None, master)
    assert unresolved.status == 'LOW_CONFIDENCE'
    assert unresolved.match is None


@pytest.mark.parametrize('extracted,canonical', [
    ('NORTHWIND, LIMITED', 'Northwind'),
    ('Contoso Inc.', 'Contoso Incorporated'),
    ('Aperture Analytics Private Limited', 'Aperture Analytics Pvt. Ltd.'),
    ('Helios-Data GmbH', 'Helios Data'),
    ('  Meridian   Markets   AG ', 'Meridian Markets'),
    ('Café Horizon Co.', 'Cafe Horizon Company'),
])
def test_legal_suffix_punctuation_and_case_variations_apply_to_other_vendors(extracted, canonical):
    assert vendor_similarity(extracted, canonical) == 99
    matched = resolve_vendor_account(extracted, None, [VendorAccount('00789', canonical, 'APAC')])
    assert matched.status == 'MATCHED'
    assert matched.match.account.vendor == canonical
    assert matched.match.account.account == '00789'


@pytest.mark.parametrize('invoice_vendor,master_vendor', [
    ('Blue Ocean Technologies LLC', 'Blue ocean'),
    ('Blu Ocean Technologies LLC', 'Blue ocean'),
    ('Bluee Ocean Technologies LLC', 'Blue ocean'),
    ('ABC Global Technology Solutions Pvt. Ltd.', 'ABC Global Technology'),
    ('ABC Global Market Data Technology Consulting LLC', 'ABC Global Market Data Technology'),
])
def test_shortened_names_support_variable_word_counts_and_one_ocr_edit(invoice_vendor, master_vendor):
    matched = resolve_vendor_account(invoice_vendor, 'APAC', [VendorAccount('00123', master_vendor, 'APAC')])
    assert matched.status == 'MATCHED'
    assert matched.match.account.vendor == master_vendor
    assert matched.match.account.account == '00123'


def test_mdm_vendor_name_comes_from_the_region_selected_record():
    master = [VendorAccount('APAC-01', 'Blue Ocean Limited', 'APAC'),
              VendorAccount('EMEA-02', 'BLUE OCEAN LTD.', 'EMEA')]
    result = InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean LLC', region='EMEA'))
    row = mdm_row(result, master)
    assert row['Vendor -As per MDM'] == 'BLUE OCEAN LTD.'
    assert row['Billing Account'] == 'EMEA-02'


@pytest.mark.parametrize('region,issue', [(None, ''), ('APAC', 'Conflicting invoice and email regions')])
def test_unresolved_mdm_vendor_keeps_extracted_name_without_guessing(region, issue):
    result = InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean Technologies, LLC', region=region,
                           service_start_date='2026-10-01', service_end_date='2026-10-31'),
                           region_match_issue=issue)
    row = mdm_row(result, accounts())
    assert row['Vendor -As per MDM'] == 'Blue Ocean Technologies, LLC'
    assert row['Billing Account'] == ''
    assert row['Billing Account match status'] == 'LOW_CONFIDENCE'
    assert row['Review status'] == 'REVIEW_REQUIRED'


def test_vendor_without_mdm_match_keeps_original_name_for_review():
    result = InvoiceResult(invoice=Invoice(vendor_name='Entirely Different Supplier Inc'))
    row = mdm_row(result, accounts())
    assert row['Vendor -As per MDM'] == 'Entirely Different Supplier Inc'
    assert row['Billing Account'] == ''
    assert row['Billing Account match status'] == 'NOT_FOUND'


def test_identical_vendor_and_restriction_with_multiple_accounts_is_low_confidence():
    master = [VendorAccount(f'CON-2026-{number:04}', 'Blue Ocean Technologies LLC', 'APAC')
              for number in (1, 21, 41, 61, 81)]
    resolution = resolve_vendor_account('Blue Ocean Technologies, LLC', 'APAC', master)
    assert resolution.status == 'LOW_CONFIDENCE'
    assert resolution.match is None
    row = mdm_row(InvoiceResult(invoice=Invoice(vendor_name='Blue Ocean Technologies, LLC',
                                               region='APAC', invoice_number='BOT-2026-1001')), master)
    assert row['Billing Account'] == ''
    assert row['Billing Account match status'] == 'LOW_CONFIDENCE'
    assert 'Multiple MDM accounts' in row['Billing Account match reason']
    assert 'CON-2026-0001' in row['Billing Account match reason']
    assert 'CON-2026-0081' in row['Billing Account match reason']


def test_no_vendor_match_is_not_found_and_master_remains_unchanged(tmp_path):
    master_path = tmp_path / 'vendor_accounts.csv'
    content = 'Account,Vendor,Restricted To\nCON-2026-0001,Blue Ocean Technologies LLC,APAC\n'
    master_path.write_text(content, encoding='utf-8')
    master = load_vendor_accounts(master_path)
    resolution = resolve_vendor_account('Entirely Different Supplier Inc', 'APAC', master)
    assert resolution.status == 'NOT_FOUND'
    assert resolution.match is None
    assert master_path.read_text(encoding='utf-8') == content


def test_region_must_match_restricted_to_before_vendor_and_account_lookup():
    master = [VendorAccount('APAC-01', 'Blue Ocean Technologies LLC', 'APAC'),
              VendorAccount('EMEA-01', 'Blue Ocean Technologies LLC', 'EMEA')]
    apac = resolve_vendor_account('Blue Ocean Technologies, LLC', 'Hong Kong', master)
    emea = resolve_vendor_account('Blue Ocean Technologies, LLC', 'EMEA', master)
    missing = resolve_vendor_account('Blue Ocean Technologies, LLC', None, master)
    assert apac.match.account.account == 'APAC-01'
    assert emea.match.account.account == 'EMEA-01'
    assert missing.match is None and missing.status == 'LOW_CONFIDENCE'


def test_blank_restriction_cannot_override_a_mismatched_region():
    master = [VendorAccount('UNRESTRICTED', 'Blue Ocean Technologies LLC', ''),
              VendorAccount('APAC-01', 'Blue Ocean Technologies LLC', 'APAC')]
    result = resolve_vendor_account('Blue Ocean Technologies LLC', 'EMEA', master)
    assert result.match is None
    assert result.status == 'LOW_CONFIDENCE'


def test_unique_vendor_ignores_region_mismatch():
    result = resolve_vendor_account(
        'Blue Ocean Technologies, LLC', 'West Palm Beach, FL',
        [VendorAccount('CON-2026-0001', 'Blue Ocean Technologies LLC', 'APAC')])
    assert result.match.account.account == 'CON-2026-0001'
    assert result.status == 'MATCHED'


def test_ambiguous_vendor_uses_region_and_reports_mismatch():
    result = resolve_vendor_account('Blue Ocean Technologies, LLC', 'West Palm Beach, FL', accounts()[:2])
    assert result.match is None
    assert result.status == 'LOW_CONFIDENCE'
    assert 'West Palm Beach, FL' in result.reason
    assert 'APAC' in result.reason


def test_unique_vendor_with_empty_restriction_still_matches():
    result = resolve_vendor_account('Blue Ocean Technologies', None,
                                    [VendorAccount('ONLY-ONE', 'Blue Ocean Technologies LLC', '')])
    assert result.status == 'MATCHED'
    assert result.match.account.account == 'ONLY-ONE'
