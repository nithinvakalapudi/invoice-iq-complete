from datetime import date

import pytest

from models.invoice_schema import Invoice, InvoiceResult
from services.mdm_csv_service import mdm_row, generate_verified_csv
from services.vendor_matching import catalog_paths, load_vendor_accounts
from services.validation_service import validate_invoice
from services.layout_values import scalar_layout_fields, money_values
from utils.date_utils import document_date


def test_service_date_heading_cannot_become_invoice_date(monkeypatch):
    from services import local_extraction_service as local
    monkeypatch.setattr(local, 'extract_document_text', lambda *_:
                        'Vendor: Example Supplier LLC\nDate(s) of Service\n10/01/26 - 10/31/26')
    payload = local.extract_invoice(b'PDF', 'invoice.pdf')
    assert 'invoice_date' not in payload['invoice']
    assert payload['invoice']['service_end_date'] == '2026-10-31'


def test_supplier_city_country_does_not_require_a_postal_number():
    from services.local_extraction_service import _vendor_region
    lines = ['Atlas Data LLC', '12 Example Street', 'London, United Kingdom',
             'Bill To:', 'Example Customer', 'Paris, France']
    assert _vendor_region(lines, 'Atlas Data LLC') == 'London, United Kingdom'


def test_explicit_alphabetic_reference_is_kept_and_address_is_not_bank_account(monkeypatch):
    from services import local_extraction_service as local
    monkeypatch.setattr(local, 'extract_document_text', lambda *_:
                        'Atlas Data LLC\n12 Example Street\nInvoice Number: SMOKE-GOOD\n')
    monkeypatch.setattr(local, '_ranked_lines', lambda *_: ['12 Example Street'])
    invoice = local.extract_invoice(b'PDF', 'invoice.pdf')['invoice']
    assert invoice['invoice_number'] == 'SMOKE-GOOD'
    assert 'bank_account_number' not in invoice


def test_document_dates_use_evidence_and_do_not_guess():
    assert document_date('01/09/2026', 'Ends 30/11/2026') == '2026-09-01'
    assert document_date('01/09/2026', 'Ends 11/30/2026') == '2026-01-09'
    assert document_date('01/09/2026', 'Nothing else dated') is None
    assert document_date('01/09/2026', '30/11/2026 and 11/30/2026') is None
    assert document_date('01/09/2026', '', 'DMY') == '2026-09-01'
    assert document_date('September 30, 2026', '') == '2026-09-30'


def test_validation_keeps_date_evidence_while_normalizing_other_fields():
    result = InvoiceResult(invoice=Invoice(invoice_date='11/30/2026',
                           service_start_date='01/09/2026', service_end_date='02/09/2026'))
    validate_invoice(result, .02, 95)
    assert result.invoice.service_start_date == '2026-01-09'
    assert result.invoice.service_end_date == '2026-02-09'


def test_configured_catalog_cannot_use_undated_files(tmp_path):
    for name in ('vendor_accounts.csv', 'contracts.csv'):
        (tmp_path / name).write_text('old', encoding='utf-8')
    with pytest.raises(ValueError, match='dated today'):
        catalog_paths(tmp_path, date(2026, 11, 1), allow_legacy=False)


def test_future_contract_is_rejected_and_not_exported_with_header_aliases(tmp_path):
    vendor = tmp_path / 'vendors.csv'
    contract = tmp_path / 'contracts.csv'
    vendor.write_text('account_number,vendor name,restricted_to\n000123,Example Vendor,APAC\n', encoding='utf-8')
    contract.write_text('contract_number,contract start date,contract end date\n000123,2099-01-01,2100-01-01\n', encoding='utf-8')
    accounts = load_vendor_accounts(vendor, contract)
    assert accounts[0].contract_status == 'NOT_STARTED'
    assert accounts[0].account == '000123'
    invoice = InvoiceResult(invoice=Invoice(vendor_name='Example Vendor', region='APAC',
                           service_start_date='2026-10-01', service_end_date='2026-10-31'),
                           validation_status='VALID', review_required=False, mdm_checked=True)
    row = mdm_row(invoice, accounts)
    assert row['Review status'] == 'REJECTED'
    assert row['Comments'] == 'Contract has not started'
    assert len(generate_verified_csv([invoice], accounts).decode('utf-8-sig').splitlines()) == 1


def test_visible_unresolved_service_periods_go_to_review():
    result = InvoiceResult(invoice=Invoice(invoice_number='A', vendor_name='Example',
                           invoice_date='2026-01-01', currency='USD', total_amount=100),
                           extraction_issues=['Multiple distinct billing/service periods; review each service line'])
    validate_invoice(result, .02, 95)
    assert result.validation_status == 'REVIEW_REQUIRED'
    assert any('Multiple distinct' in error for error in result.errors)


def test_decimal_comma_summary_uses_arithmetic_and_column_context():
    def word(x, y, text):
        return (x, y, x + len(text) * 5, y + 10, text)
    words = [word(200, 80, 'Net'), word(240, 80, 'worth'), word(300, 80, 'VAT'),
             word(400, 80, 'Gross'), word(450, 80, 'worth'), word(50, 120, 'Total'),
             word(200, 120, '1 000,00'), word(300, 120, '200,00'), word(400, 120, '1 200,00')]
    assert scalar_layout_fields(words, 595) == {'subtotal': '1000.00', 'tax_amount': '200.00', 'total_amount': '1200.00'}
    assert money_values('GBP 1,743.19 and EUR 1.743,19') == ['1743.19', '1743.19']


def test_tax_table_row_uses_amount_column_instead_of_quantity_or_percentage():
    def word(x, y, text):
        return (x, y, x + len(text) * 5, y + 10, text)
    words = [word(400, 80, 'Quantity'), word(500, 80, 'Total'),
             word(50, 120, 'Value'), word(80, 120, 'Added'), word(110, 120, 'Tax'),
             word(200, 120, '20%'), word(400, 120, '1.00'), word(500, 120, '290.53')]
    assert scalar_layout_fields(words, 595)['tax_amount'] == '290.53'
