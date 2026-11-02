"""Additional cumulative invoice workflow CSV, separate from the original report."""
import csv
import io
from datetime import datetime, timezone

from models.invoice_schema import InvoiceResult
from services.csv_service import _display_date, _invoice_age, _line_quantity_total, invoice_date_display, invoice_age
from services.validation_service import (REQUIRED_FIELDS, REQUIRED_FIELD_LABELS,
                                         effective_errors, effective_validation_status,
                                         service_date_rejection_reason)
from services.vendor_matching import VendorAccount, VendorResolution, resolve_vendor_account
from utils.number_utils import decimal_or_none


REPORT_NAME = 'MDM/Invoice_data.csv'
VERIFIED_REPORT_NAME = 'MDM/Contract_verified_invoices.csv'
LEGACY_DRAFT_WARNING = 'Local OCR/model draft has no calibrated confidence; verify every field against the source invoice.'
COLUMNS = [
    'Vendor -As per MDM', 'Billing Account',
    'Invoice Number (As per Invoice)', 'Invoice Number', 'Invoice Date',
    'Currency', 'Billing Start Date', 'Billing End Date',
    'Net Amount', 'Tax Amount', 'Invoice Received Date', 'Sent for Scanning Date',
    'Scanned Date in Expense', 'Ageing (In Days)',
    'Ageing (Today-Sent For Scanning Date)', 'Comments',
]
VERIFIED_COLUMNS = [
    'Insert or Update', 'Vendor', 'Billing Account', 'Invoice Number',
    'Invoice Date', 'Currency', 'Start Date', 'End Date', 'Net Amount',
    'Tax Amount', 'Description', 'Date Entered', 'Approved On Date',
]
DISPLAY_COLUMNS = COLUMNS + [
    'Billing Account match status', 'Billing Account match reason',
    'Contract check status', 'Contract check reason', 'Contract Start Date', 'Contract End Date',
    'Region', 'Service line count', 'Service descriptions', 'Service quantities', 'Total quantity',
    'Extraction completeness (%)', 'Review status', 'Review reasons', 'Duplicate status',
    'Source', 'Source email', 'Email file', 'Source attachment',
    'Processing result', 'Action',
]
EXPECTED_EXTRACTED_FIELDS = (
    'vendor_name', 'invoice_number', 'invoice_date', 'currency',
    'service_start_date', 'service_end_date', 'subtotal', 'tax_amount', 'total_amount',
)


def extraction_completeness(result: InvoiceResult) -> float:
    """Field coverage, not a claim that the values are correct."""
    invoice = result.invoice
    present = sum(getattr(invoice, field, None) not in (None, '')
                  for field in EXPECTED_EXTRACTED_FIELDS)
    return round(present * 100 / len(EXPECTED_EXTRACTED_FIELDS), 2)


def _source_email(value: str | None) -> str:
    """Do not export synthetic-domain placeholders as company contacts."""
    if not value or '@' not in value:
        return ''
    domain = value.rsplit('@', 1)[1].casefold()
    return '' if domain.endswith(('.test', '.example', '.invalid')) else value


def _received_date(processed_at: str) -> str:
    """Keep the local date of intake, rather than reusing invoice/service dates."""
    try:
        received = datetime.fromisoformat(processed_at.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return ''
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    return received.astimezone().strftime('%m/%d/%Y')


def review_reasons(result: InvoiceResult, account_resolution: VendorResolution | None = None) -> list[str]:
    """Explain review decisions without treating every blank output cell as required."""
    if result.processing_status == 'FAILED':
        return result.errors or ['Document processing failed']
    if result.processing_status == 'SKIPPED' or (
        not result.review_required and effective_validation_status(result) == 'VALID'
        and result.duplicate_status != 'POSSIBLE_DUPLICATE'
        and (account_resolution is None or account_resolution.status == 'MATCHED')
        and (account_resolution is None or account_resolution.match is None
             or account_resolution.match.account.contract_status in {'PRESENT', 'NOT_CHECKED'})
    ):
        return []
    missing = [REQUIRED_FIELD_LABELS[name] for name in REQUIRED_FIELDS
               if getattr(result.invoice, name, None) in (None, '')]
    reasons = [f"Missing required: {', '.join(missing)}"] if missing else []
    reasons.extend(error for error in effective_errors(result)
                   if not error.startswith('Missing required field:'))
    if account_resolution is not None and account_resolution.status != 'MATCHED':
        reasons.append('Billing Account: ' + account_resolution.reason)
    if account_resolution is not None and account_resolution.match is not None:
        contract = account_resolution.match.account
        if contract.contract_status not in {'PRESENT', 'NOT_CHECKED'}:
            reasons.append('Contract: ' + contract.contract_reason)
    if result.duplicate_status == 'POSSIBLE_DUPLICATE' and not any(
        'duplicate' in reason.casefold() for reason in reasons
    ):
        reasons.append('Possible duplicate invoice')
    if result.processing_status == 'LOCAL_DRAFT' and result.review_required and (
        result.duplicate_status != 'POSSIBLE_DUPLICATE'
    ):
        reasons.append('Local extraction has no calibrated field confidence; verify against the invoice')
    elif result.processing_status == 'OCR_ONLY':
        reasons.append('OCR text was read, but invoice fields need verification')
    elif result.processing_status == 'IMPORTED':
        reasons.append('Imported row needs verification against the source invoice')
    if not reasons and result.review_required:
        reasons.append('Validation requires manual review')
    return list(dict.fromkeys(reasons))


def mdm_row(result: InvoiceResult, vendor_accounts: list[VendorAccount] | None = None) -> dict:
    """One source of truth for the on-screen and exported MDM columns."""
    invoice = result.invoice
    if result.mdm_checked is False:
        vendor_accounts = None
    mdm_checked = vendor_accounts is not None
    account_resolution = resolve_vendor_account(invoice.vendor_name, invoice.region,
                                                vendor_accounts or [], contract_id=invoice.contract_id)
    if result.region_match_issue:
        account_resolution = VendorResolution(None, 'LOW_CONFIDENCE', result.region_match_issue)
    account_match = account_resolution.match
    contract = account_match.account if account_match else None
    # Workflow/MDM values are deliberately empty without an authoritative source.
    row = {column: '' for column in DISPLAY_COLUMNS}
    comments = invoice.invoice_comments or ''
    rejection_reason = service_date_rejection_reason(result)
    expired_contract = mdm_checked and contract is not None and contract.contract_status == 'EXPIRED'
    not_started = mdm_checked and contract is not None and contract.contract_status == 'NOT_STARTED'
    rejected = effective_validation_status(result) == 'REJECTED' or expired_contract or not_started
    if rejection_reason and rejection_reason.casefold() not in comments.casefold():
        comments = f'{comments.rstrip(" ;")}; {rejection_reason}' if comments else rejection_reason
    if contract is not None and contract.contract_status in {
        'NOT_FOUND', 'MISSING_DATES', 'INVALID_DATES', 'INVALID_MASTER', 'EXPIRED', 'NOT_STARTED'
    }:
        validity_comment = ('Contract expired' if expired_contract else
                            'Contract has not started' if not_started else 'Contract is not valid')
        if validity_comment.casefold() not in comments.casefold():
            comments = f'{comments.rstrip(" ;")}; {validity_comment}' if comments else validity_comment
    scanning_date = _received_date(result.processed_at)
    needs_review = (result.processing_status != 'SKIPPED' and
                    (result.review_required or result.validation_status != 'VALID'
                     or result.duplicate_status == 'POSSIBLE_DUPLICATE'
                     or (mdm_checked and account_resolution.status != 'MATCHED')
                     or (contract is not None and contract.contract_status not in {'PRESENT', 'NOT_CHECKED'})))
    row.update({
        'Region': invoice.region or '',
        # Use the master spelling only after the vendor/account is resolved;
        # keep invoice.vendor_name unchanged as the original extraction.
        'Vendor -As per MDM': account_match.account.vendor if account_match else (invoice.vendor_name or ''),
        'Billing Account': account_match.account.account if account_match else '',
        'Billing Account match status': account_resolution.status if result.mdm_checked is not False else '',
        'Billing Account match reason': account_resolution.reason if result.mdm_checked is not False else '',
        'Contract check status': (contract.contract_status if contract else 'NOT_CHECKED') if result.mdm_checked is not False else '',
        'Contract check reason': (contract.contract_reason if contract else ''),
        'Contract Start Date': (contract.contract_start_date if contract else ''),
        'Contract End Date': (contract.contract_end_date if contract else ''),
        'Invoice Number (As per Invoice)': invoice.invoice_number or '',
        'Invoice Number': invoice.invoice_number or '',
        'Invoice Date': invoice_date_display(result, 'invoice_date'),
        'Currency': invoice.currency or '',
        'Billing Start Date': invoice_date_display(result, 'service_start_date'),
        'Billing End Date': invoice_date_display(result, 'service_end_date'),
        'Service line count': len(result.line_items) if result.line_items else '',
        'Service descriptions': '; '.join(item.description.strip() for item in result.line_items
                                          if item.description),
        'Service quantities': '; '.join(str(item.quantity) for item in result.line_items
                                         if item.quantity not in (None, '')),
        'Total quantity': _line_quantity_total(result),
        'Net Amount': decimal_or_none(invoice.subtotal),
        'Tax Amount': decimal_or_none(invoice.tax_amount),
        'Invoice Received Date': _received_date(result.processed_at),
        'Sent for Scanning Date': scanning_date,
        'Scanned Date in Expense': scanning_date,
        'Ageing (In Days)': invoice_age(result),
        'Ageing (Today-Sent For Scanning Date)': _invoice_age(scanning_date),
        'Comments': comments,
        'Extraction completeness (%)': extraction_completeness(result),
        'Review status': ('SKIPPED' if result.processing_status == 'SKIPPED' else
                          'REJECTED' if rejected else
                          'REVIEW_REQUIRED' if needs_review else 'SUCCESS'),
        'Review reasons': '; '.join(review_reasons(result, account_resolution if mdm_checked else None)),
        'Duplicate status': result.duplicate_status,
        'Source': result.source_file,
        'Source email': _source_email(invoice.vendor_email),
        'Email file': result.source_email,
        'Source attachment': result.source_attachment,
        # Processing succeeded even when extracted values still require review.
        'Processing result': ('SUCCESS' if result.processing_status in {'PROCESSED', 'LOCAL_DRAFT'}
                              else result.processing_status),
        'Action': ('Skipped' if result.processing_status == 'SKIPPED' else
                   'Rejected' if rejected else
                   'Review Required' if needs_review else 'No Review Required'),
    })
    return row


def generate_mdm_csv(results: list[InvoiceResult],
                     vendor_accounts: list[VendorAccount] | None = None,
                     *, success_only: bool = False) -> bytes:
    """Render MDM rows; the delivery CSV can opt into the success-only gate."""
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    for result in results:
        row = mdm_row(result, vendor_accounts)
        if success_only and (row['Review status'] != 'SUCCESS' or row['Contract check status'] != 'PRESENT'):
            continue
        writer.writerow({column: row[column] for column in COLUMNS})
    return output.getvalue().encode('utf-8-sig')


def generate_verified_csv(results: list[InvoiceResult],
                          vendor_accounts: list[VendorAccount] | None = None) -> bytes:
    """Export only validated invoices with an unambiguous, dated MDM contract.

    Rebuild from saved results each time so refreshing reports cannot append a
    duplicate row. This is an insert feed, not an approval action in an ERP.
    """
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=VERIFIED_COLUMNS)
    writer.writeheader()
    for result in results:
        row = mdm_row(result, vendor_accounts)
        if row['Contract check status'] != 'PRESENT' or row['Review status'] != 'SUCCESS':
            continue
        writer.writerow({
            'Insert or Update': 'Insert',
            'Vendor': row['Vendor -As per MDM'],
            'Billing Account': row['Billing Account'],
            'Invoice Number': row['Invoice Number'],
            'Invoice Date': row['Invoice Date'],
            'Currency': row['Currency'],
            'Start Date': row['Billing Start Date'],
            'End Date': row['Billing End Date'],
            'Net Amount': row['Net Amount'],
            'Tax Amount': row['Tax Amount'],
            'Description': row['Service descriptions'],
            'Date Entered': row['Invoice Received Date'],
            'Approved On Date': _received_date(result.processed_at),
        })
    return output.getvalue().encode('utf-8-sig')
