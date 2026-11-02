"""Exercise the real upload, MDM, check and download routes in isolated storage."""
from __future__ import annotations

import csv
import io
import json
import random
import tempfile
from dataclasses import replace
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pymupdf
from fastapi.testclient import TestClient

import web_app
from config.ui_settings import UiSettings, save_ui_settings
from evaluation.kaggle_invoices import download
from services.local_storage import _atomic_write
from training.local_pilot import _exact_match


def make_pdf(number, missing_dates=False, conflicting=False):
    lines = ['Atlas Data LLC', '12 Example Street', 'London, United Kingdom',
             'Bill To: Example Customer Ltd', f'Invoice Number: {number}',
             'Invoice Date: 2026-11-01', 'Currency: USD',
             'Service Period Description Qty Rate / Unit Amount']
    if not missing_dates:
        lines.append('2026-11-01 - 2026-11-30 Data Access 1 $100.00 $100.00')
    else:
        lines.append('Data Access 1 $100.00 $100.00')
    if conflicting:
        lines.append('2026-12-01 - 2026-12-31 Extra Period 0 $0.00 $0.00')
    lines.extend(['Subtotal: $100.00', 'Tax: $20.00', 'Amount Due (USD): $120.00'])
    with pymupdf.open() as book:
        page = book.new_page()
        for index, line in enumerate(lines):
            page.insert_text((40, 40 + index * 22), line, fontsize=10)
        return book.tobytes()


def run(root=Path('evaluation_data/upload_smoke')):
    labels = download('batch_1/batch_1/batch1_1.csv', root / 'labels.csv')
    with labels.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    already_evaluated = {path.name for path in Path('evaluation_data/kaggle_sample/images').glob('*.jpg')}
    selected = random.Random(20261101).sample([row for row in rows if row['File Name'] not in already_evaluated], 5)
    uploads, expected = [], {}
    for row in selected:
        filename = row['File Name']
        path = download('batch_1/batch_1/batch1_1/' + filename, root / filename)
        uploads.append(('files', (filename, path.read_bytes(), 'image/jpeg')))
        label = json.loads(row['Json Data'])
        expected[filename] = {'vendor_name': label['invoice']['seller_name'],
                              'customer_name': label['invoice']['client_name'],
                              'invoice_number': label['invoice']['invoice_number'],
                              'invoice_date': label['invoice']['invoice_date'],
                              'total_amount': label['subtotal']['total'],
                              'tax_amount': label['subtotal']['tax']}
    for name, missing, conflict in [('SMOKE-GOOD', False, False), ('SMOKE-NO-DATES', True, False),
                                    ('SMOKE-CONFLICT', False, True)]:
        data = make_pdf(name, missing, conflict)
        _atomic_write(root / (name + '.pdf'), data)
        uploads.append(('files', (name + '.pdf', data, 'application/pdf')))
    with pymupdf.open(stream=make_pdf('SMOKE-SCANNED'), filetype='pdf') as book:
        scanned = book[0].get_pixmap(dpi=180).tobytes('png')
    _atomic_write(root / 'SMOKE-SCANNED.png', scanned)
    uploads.append(('files', ('SMOKE-SCANNED.png', scanned, 'image/png')))
    mail = EmailMessage()
    mail['From'] = 'billing@example.invalid'
    mail['To'] = 'ap@example.invalid'
    mail['Subject'] = 'Synthetic upload test: two invoice attachments'
    mail.set_content('Synthetic test data only. Do not pay.')
    for number, missing in [('SMOKE-EMAIL-GOOD', False), ('SMOKE-EMAIL-NO-DATES', True)]:
        mail.add_attachment(make_pdf(number, missing), maintype='application', subtype='pdf',
                            filename=number + '.pdf')
    uploads.append(('files', ('two-invoice-email.eml', mail.as_bytes(), 'message/rfc822')))
    for number in ('SMOKE-GOOD', 'SMOKE-SCANNED', 'SMOKE-EMAIL-GOOD'):
        suffix = '.png' if number == 'SMOKE-SCANNED' else '.pdf'
        expected[number + suffix] = {'vendor_name': 'Atlas Data LLC',
            'customer_name': 'Example Customer Ltd', 'invoice_number': number,
            'invoice_date': '2026-11-01', 'currency': 'USD',
            'service_start_date': '2026-11-01', 'service_end_date': '2026-11-30',
            'subtotal': '100.00', 'tax_amount': '20.00', 'total_amount': '120.00',
            'region': 'London, United Kingdom'}
    with tempfile.TemporaryDirectory(prefix='invoice-upload-smoke-') as temp:
        base = Path(temp)
        settings = replace(web_app.settings, local_storage_dir=str(base / 'internal'))
        mdm = base / 'masters'
        mdm.mkdir()
        stamp = datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d')
        (mdm / f'InvoiceMDM_{stamp}.csv').write_text(
            'Account Number,Vendor,Restricted To\nSMOKE-ACCOUNT,Atlas Data LLC,EMEA\n', encoding='utf-8')
        (mdm / f'contracts_{stamp}.csv').write_text(
            'Contract ID,Start Date,End Date\nSMOKE-ACCOUNT,2026-01-01,2030-12-31\n', encoding='utf-8')
        save_ui_settings(settings, UiSettings(output_folder=str(base / 'output'), mdm_folder=str(mdm)))
        with patch.object(web_app, 'settings', settings), TestClient(web_app.app) as client:
            response = client.post('/api/process', files=uploads)
            response.raise_for_status()
            batch = response.json()
            request = {'batch_id': batch['batch_id'], 'generation': batch['generation']}
            mdm_response = client.post('/api/mdm/run', json=request)
            mdm_response.raise_for_status()
            processed = mdm_response.json()
            check_response = client.post('/api/mdm/check', json=request)
            check_response.raise_for_status()
            records, mismatches, unresolved_dates = [], [], []
            for item in processed['results']:
                actual = item['invoice']
                filename = item['source_file']
                checks = {}
                for field, gold in expected.get(filename, {}).items():
                    checks[field] = _exact_match(str(gold), actual.get(field), field)
                    if not checks[field]:
                        difference = {'file': filename, 'field': field, 'expected': gold,
                                      'actual': actual.get(field)}
                        if field == 'invoice_date' and any('ambiguous date order' in error for error in item['errors']):
                            unresolved_dates.append(difference)
                        else:
                            mismatches.append(difference)
                records.append({'file': filename, 'processing_status': item['processing_status'],
                                'validation_status': item['validation_status'],
                                'invoice': actual, 'mdm_row': item['mdm_row'],
                                'errors': item['errors'], 'checks': checks})
            csv_response = client.get('/api/download/history/MDM/Invoice_data.csv')
            csv_response.raise_for_status()
            csv_data = csv_response.content
            exported = list(csv.DictReader(io.StringIO(csv_data.decode('utf-8-sig'))))
            duplicate = client.post('/api/process', files=[('files', (
                'SMOKE-GOOD.pdf', make_pdf('SMOKE-GOOD'), 'application/pdf'))])
            duplicate.raise_for_status()
            duplicate_record = duplicate.json()['results'][0]
            contract = mdm / f'contracts_{stamp}.csv'
            contract.write_text('Contract ID,Start Date,End Date\nSMOKE-ACCOUNT,2020-01-01,2020-12-31\n', encoding='utf-8')
            expired = client.post('/api/mdm/run', json=request)
            expired.raise_for_status()
            expired_good = next(item for item in expired.json()['results'] if item['source_file'] == 'SMOKE-GOOD.pdf')
            expired_csv = client.get('/api/download/history/MDM/Invoice_data.csv')
            expired_csv.raise_for_status()
            expired_rows = list(csv.DictReader(io.StringIO(expired_csv.content.decode('utf-8-sig'))))
            workflow_checks = {
                'all_attachments_returned': len(records) == 11,
                'no_processing_failures': all(item['processing_status'] != 'FAILED' for item in records),
                'only_valid_invoices_exported': {row.get('Invoice Number') for row in exported}
                    == {'SMOKE-GOOD', 'SMOKE-SCANNED', 'SMOKE-EMAIL-GOOD'},
                'duplicate_flagged': duplicate_record['duplicate_status'] == 'POSSIBLE_DUPLICATE',
                'expired_contract_rejected': expired_good['mdm_row']['Review status'] == 'REJECTED',
                'expired_invoice_excluded_from_export': len(expired_rows) == 0,
            }
            report = {'test_storage': 'Temporary; live history was not modified',
                      'extraction_backend': client.get('/api/config').json()['extraction_backend'],
                      'dataset_selection': 'Five seeded random images outside the prior 60-image sample',
                      'upload_http': response.status_code, 'mdm_http': mdm_response.status_code,
                      'check_http': check_response.status_code, 'download_http': csv_response.status_code,
                      'workflow_checks': workflow_checks,
                      'documents': len(records), 'mismatches': mismatches,
                      'unresolved_dates': unresolved_dates,
                      'exported_invoice_numbers': [row.get('Invoice Number') for row in exported],
                      'records': records}
    _atomic_write(root / 'report.json', json.dumps(report, indent=2).encode())
    if mismatches or not all(workflow_checks.values()):
        raise AssertionError(f'Upload workflow checks failed; inspect {root / "report.json"}')
    return {key: value for key, value in report.items() if key != 'records'} | {
        'statuses': [{key: row[key] for key in ('file', 'processing_status', 'validation_status')}
                     for row in records]}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
