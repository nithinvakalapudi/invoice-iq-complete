"""Acceptance checks for the generated, local-only MDM invoice/email fixtures."""
import csv
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

import pytest

from config.settings import settings
from services.document_processing import process_document
from services.eml_service import extract_eml_attachments
from services.local_extraction_service import extract_invoice
from services.mdm_csv_service import mdm_row
from services.vendor_matching import load_vendor_accounts


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'local_data' / 'generated_demo_2026-10-09' / 'manifest.csv'
MASTER = ROOT / 'local_data' / 'MDM' / 'vendor_accounts.csv'


@pytest.mark.skipif(not MANIFEST.exists(), reason='Demo fixture set has not been generated')
def test_generated_emails_and_invoices_match_mdm_end_to_end():
    with MANIFEST.open(encoding='utf-8', newline='') as source:
        rows = list(csv.DictReader(source))
    accounts = load_vendor_accounts(MASTER, MASTER.with_name('contracts.csv'))
    assert len(rows) == 10
    assert len({row['Invoice Number'] for row in rows}) == len(rows)
    assert len({row['Email'] for row in rows}) == len(rows)
    for expected in rows:
        email_path = Path(expected['Email'])
        pdf_path = Path(expected['PDF'])
        if email_path.exists():
            email_bytes = email_path.read_bytes()
        else:
            # Reset may remove the local Outlook demo inbox. Rebuild the same
            # message in memory so this acceptance test never repopulates it.
            message = EmailMessage()
            message['From'] = f"{expected['Vendor']} Billing <{expected['Vendor Email']}>"
            message['To'] = 'Demo Accounts Payable <ap@invoice-demo.example.com>'
            message['Subject'] = f"SYNTHETIC TEST invoice {expected['Invoice Number']}"
            message.set_content(f"Vendor region: {expected['Vendor Region']}\n"
                                f"Service: {expected['Service Specification']}\n")
            message.add_attachment(pdf_path.read_bytes(), maintype='application',
                                   subtype='pdf', filename=pdf_path.name)
            email_bytes = message.as_bytes()
        message = BytesParser(policy=policy.default).parsebytes(email_bytes)
        assert expected['Vendor Email'] in message['From']
        assert 'ap@invoice-demo.example.com' in message['To']
        assert expected['Invoice Number'] in message['Subject']
        assert expected['Service Specification'] in message.get_body(preferencelist=('plain',)).get_content()
        documents = extract_eml_attachments(email_path.name, email_bytes,
                                            settings.max_file_mb * 1024 * 1024)
        assert len(documents) == 1
        document = documents[0]
        assert document.filename == pdf_path.name
        assert document.data == pdf_path.read_bytes()
        assert document.source_email == email_path.name
        payload = extract_invoice(document.data, document.filename)
        fields = payload['invoice']
        assert fields['vendor_name'] == expected['Vendor']
        assert fields['invoice_number'] == expected['Invoice Number']
        assert fields['vendor_email'] == expected['Vendor Email']
        assert fields['region'] == expected['Vendor Region']
        assert fields['currency'] == expected['Currency']
        assert fields['subtotal'] == expected['Net Amount']
        assert fields['tax_amount'] == expected['Tax Amount']
        assert fields['service_start_date'] == '2026-10-01'
        assert fields['service_end_date'] == '2026-10-31'
        assert len(payload['line_items']) == 2
        assert '; '.join(item['description'] for item in payload['line_items']) == expected['Service Specification']
        result = process_document(document, 0.02, 95)
        report = mdm_row(result, accounts)
        assert report['Billing Account'] == expected['Account']
        assert report['Billing Account match status'] == 'MATCHED'
        matched = next(account for account in accounts if account.account == expected['Account'])
        assert report['Review status'] == ('REJECTED' if matched.contract_status == 'EXPIRED' else 'SUCCESS')
        assert report['Service line count'] == 2
        assert report['Source email'] == expected['Vendor Email']


@pytest.mark.skipif(not MANIFEST.exists(), reason='Demo fixture set has not been generated')
def test_master_preserves_original_data_and_has_demo_metadata():
    backup = MASTER.with_name('vendor_accounts.before_demo_2026-10-09.csv')
    with backup.open(encoding='utf-8-sig', newline='') as source:
        before = list(csv.DictReader(source))
    with MASTER.open(encoding='utf-8-sig', newline='') as source:
        after = list(csv.DictReader(source))
    assert len(before) == len(after) == 100
    for original, enriched in zip(before, after):
        # People may edit names and dates in the master after fixture creation;
        # the stable account IDs and added metadata are the relevant contract.
        assert enriched['Account'] == original['Account']
        assert enriched['Vendor Region']
        assert enriched['Vendor Address']
        assert enriched['Service Specification']
        assert enriched['Vendor Email'].endswith('.example.com')


def test_demo_master_has_one_region_per_account_for_each_vendor():
    with MASTER.open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source))
    groups = {}
    for row in rows:
        canonical = row['Description'].removesuffix(' Managed Services Agreement')
        groups.setdefault(canonical, []).append(row)
    assert len(groups) == 20
    assert all(len(group) == 5 for group in groups.values())
    assert all(len({row['Restricted To'] for row in group}) == 5 for group in groups.values())
    blue_ocean = groups['Blue Ocean Technologies LLC']
    assert blue_ocean[0]['Vendor'] == 'Blue Ocean'
    assert blue_ocean[0]['Vendor Alias'] == 'Blue Ocean Technologies LLC'
