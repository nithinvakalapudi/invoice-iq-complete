"""UI-independent processing shared by uploads and extracted MSG files."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from config.settings import settings
from models.invoice_schema import InvoiceResult
from services.local_extraction_service import extract_invoice
from services.validation_service import REQUIRED_FIELDS, apply_service_date_policy, validate_invoice
from services.vendor_matching import _region_key
from utils.file_utils import DocumentInput


def _rule_validated_local_invoice(result: InvoiceResult, payload: dict) -> bool:
    """Accept a complete, arithmetically checked local extraction without inventing confidence."""
    invoice = result.invoice
    derived = payload.get('_derived_fields') or []
    if derived:
        if derived != ['subtotal'] or not result.line_items:
            return False
        try:
            # The unprinted net amount is supported by two independent paths:
            # printed total minus printed tax, and the sum of printed line items.
            if sum((Decimal(str(item.line_total)) for item in result.line_items), Decimal('0')) != Decimal(str(invoice.subtotal)):
                return False
        except (InvalidOperation, TypeError, ValueError):
            return False
    return (
        not result.errors
        and all(getattr(invoice, field, None) not in (None, '') for field in REQUIRED_FIELDS)
        and all(getattr(invoice, field, None) not in (None, '')
                for field in ('subtotal', 'tax_amount', 'total_amount'))
        and bool(result.line_items)
        and all(item.description and item.quantity not in (None, '')
                and item.unit_price not in (None, '') and item.line_total not in (None, '')
                for item in result.line_items)
    )


def process_document(document: DocumentInput, tolerance: float, threshold: float) -> InvoiceResult:
    timestamp = datetime.now(timezone.utc).isoformat()
    if document.intake_status:
        result = InvoiceResult.failed(document.filename, document.intake_message, timestamp)
        if document.intake_status == 'SKIPPED':
            result.processing_status = result.validation_status = 'SKIPPED'
            result.review_required = False
            result.warnings, result.errors = result.errors, []
    else:
        try:
            # Only attachment bytes and its filename cross the extraction boundary.
            payload = extract_invoice(document.data, document.filename)
            result = InvoiceResult.from_ai_payload(payload, document.filename, timestamp,
                                                   getattr(settings, 'minimum_field_confidence', 95.0))
            invoice_region = result.invoice.region
            email_region = document.email_region
            result.region_match_issue = document.email_region_issue
            if invoice_region and email_region and _region_key(invoice_region) != _region_key(email_region):
                result.region_match_issue = (
                    f"Invoice Region '{invoice_region}' conflicts with email Region '{email_region}'")
            elif not invoice_region and email_region and not result.region_match_issue:
                result.invoice.region = email_region
            validate_invoice(result, tolerance, threshold)
            if payload.get('_local_draft'):
                # Only a separately calibrated field model could support an
                # automatic pass. The current OCR/line selector supplies no
                # calibrated scores, so its drafts always require review.
                confidence_limit = max(95.0, threshold)
                populated = [key for key, value in result.invoice.to_dict().items()
                             if value not in (None, '')]
                auto_valid = (payload.get('_confidence_calibrated') is True
                              and result.extraction_confidence > confidence_limit
                              and not result.errors and not result.line_items
                              and not payload.get('_derived_fields')
                              and all(result.field_confidence.get(key, 0) > confidence_limit
                                      for key in populated))
                if auto_valid:
                    result.processing_status = 'PROCESSED'
                    result.validation_status = 'VALID'
                    result.review_required = False
                elif _rule_validated_local_invoice(result, payload):
                    result.processing_status = 'LOCAL_DRAFT'
                    result.validation_status = 'VALID'
                    result.review_required = False
                    result.warnings = [warning for warning in result.warnings
                                       if not warning.startswith('Low-confidence extraction')]
                    result.warnings.append(
                        'Passed required-field, line-item, and amount checks; extraction accuracy is not independently calibrated.')
                    if payload.get('_derived_fields') == ['subtotal']:
                        result.warnings.append(
                            'Net amount equals both printed total minus printed tax and the sum of printed line items.')
                else:
                    result.processing_status = 'LOCAL_DRAFT'
                    result.validation_status = 'REVIEW_REQUIRED'
                    result.review_required = True
                    result.warnings = [warning for warning in result.warnings
                                       if not warning.startswith('Low-confidence extraction')]
                    if 'subtotal' in payload.get('_derived_fields', []):
                        result.warnings.append('Net amount was calculated as total minus tax; verify discounts and other charges.')
            elif payload.get('_ocr_only'):
                result.processing_status = 'OCR_ONLY'
                result.validation_status = 'REVIEW_REQUIRED'
                result.review_required = True
                result.warnings = [warning for warning in result.warnings
                                   if not warning.startswith('Low-confidence extraction')]
                result.warnings.append('OCR completed; local field extraction is not validated. Review the source and enter invoice fields manually.')
            if result.region_match_issue:
                result.errors.append(result.region_match_issue)
                result.review_required = True
                result.validation_status = 'REVIEW_REQUIRED'
        except Exception as exc:
            result = InvoiceResult.failed(document.filename, str(exc), timestamp)
    result.source_email = document.source_email
    result.source_attachment = document.source_attachment
    result.attachment_index = document.attachment_index
    return apply_service_date_policy(result)
