"""Reconstructed PDF layouts exercise extraction, not photograph transcription."""
import pymupdf

from services.pdf_layout_fields import extract_layout_fields
from services.local_extraction_service import extract_invoice


def pdf(words):
    with pymupdf.open() as book:
        page = book.new_page()
        for x, y, text in words:
            page.insert_text((x, y), text, fontsize=10)
        return book.tobytes()


def test_billing_period_is_selected_instead_of_contract_period():
    data = pdf([(50, 100, 'Description'), (200, 100, 'Contract'),
                (200, 112, 'Period'), (300, 100, 'Billing'), (300, 112, 'Period'),
                (400, 100, 'Net'), (200, 140, '30/09/2026'), (200, 152, '29/09/2027'),
                (300, 140, '30/09/2026'), (300, 152, '29/10/2026'),
                (200, 180, '30/09/2026'), (200, 192, '29/09/2027'),
                (300, 180, '30/09/2026'), (300, 192, '29/10/2026')])
    assert extract_layout_fields(data) == {'service_start_date': '2026-09-30',
                                         'service_end_date': '2026-10-29'}


def test_split_service_columns_and_amount_due():
    data = pdf([(50, 30, 'Vendor: Example Supplier LLC'),
                (50, 50, 'Invoice Number: INV-123'),
                (200, 100, 'For Service'), (200, 112, 'Starting'),
                (300, 100, 'For Service'), (300, 112, 'Ending'), (400, 100, 'Quantity'),
                (200, 140, '01/09/2026'), (300, 140, '30/11/2026'),
                (200, 180, '01/09/2026'), (300, 180, '30/11/2026'),
                (50, 250, 'Amount Due (GBP) 1,743.19')])
    invoice = extract_invoice(data, 'split-columns.pdf')['invoice']
    assert invoice['service_start_date'] == '2026-09-01'
    assert invoice['service_end_date'] == '2026-11-30'
    assert invoice['total_amount'] == '1743.19'


def test_different_billing_periods_are_not_collapsed():
    data = pdf([(50, 100, 'Description'), (300, 100, 'Billing'), (300, 112, 'Period'),
                (400, 100, 'Net'), (300, 140, '30/09/2026'), (300, 152, '29/10/2026'),
                (300, 180, '30/09/2026'), (300, 192, '29/09/2027')])
    assert 'Multiple distinct' in extract_layout_fields(data)['_service_period_issue']


def test_conflicting_columns_cannot_fall_back_to_first_contract_range():
    data = pdf([(50, 30, 'Vendor: Example Supplier LLC'),
                (50, 50, 'Contract period 01/01/2026 - 12/31/2026'),
                (50, 100, 'Description'), (300, 100, 'Billing'), (300, 112, 'Period'),
                (400, 100, 'Net'), (300, 140, '30/09/2026'), (300, 152, '29/10/2026'),
                (300, 180, '30/09/2026'), (300, 192, '29/09/2027')])
    result = extract_invoice(data, 'conflict.pdf')
    assert not result['invoice'].get('service_start_date')
    assert not result['invoice'].get('service_end_date')
    assert result['_extraction_issues']
