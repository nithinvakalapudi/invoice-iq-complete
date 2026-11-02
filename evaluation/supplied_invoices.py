"""Offline regression of supplied invoice archives without changing live data.

Answer sheets are comparison data only. Uploaded scripts are never executed,
and results from a training corpus are not independent generalization accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
import zipfile

from config.settings import settings
from evaluation.reporting import csv_bytes
from models.invoice_schema import InvoiceResult
from services.document_processing import process_document
from services.duplicate_service import mark_duplicates
from services.local_extraction_service import DATE_RE, _pilot, _reviewed_model
from services.local_storage import LocalStorage, _excel_bytes, _restore
from services.mdm_csv_service import COLUMNS, generate_mdm_csv, generate_verified_csv, mdm_row
from training.local_pilot import _safe_archive_members
from utils.date_utils import normalize_date
from utils.file_utils import MAX_ZIP_DOCUMENTS, SUPPORTED_EXTENSIONS, expand_upload
from utils.number_utils import to_decimal


REFERENCE_FIELDS = {
    'vendor_name': 'vendor_name', 'vendor_address': 'vendor_address',
    'customer_name': 'customer_name', 'customer_address': 'customer_address',
    'invoice_number': 'invoice_number', 'invoice_date': 'invoice_date',
    'due_date': 'due_date', 'currency': 'currency', 'account_number': 'bank_account_number',
    'subtotal': 'subtotal', 'discount': 'discount', 'tax_amount': 'tax_amount',
    'shipping_amount': 'shipping_amount', 'total_amount': 'total_amount',
    'payment_terms': 'payment_terms', 'contact_email': 'customer_email',
    'service_start_date': 'service_start_date', 'service_end_date': 'service_end_date',
}
NUMBERS = {'subtotal', 'discount', 'tax_amount', 'shipping_amount', 'total_amount',
           'quantity', 'unit_price', 'line_total'}
DATES = {'invoice_date', 'due_date', 'service_start_date', 'service_end_date'}
CORE = {'vendor_name', 'invoice_number', 'invoice_date', 'currency',
        'subtotal', 'tax_amount', 'total_amount', 'service_start_date', 'service_end_date'}


def _normalized(field, value):
    if value is None or not str(value).strip():
        return None
    if field in NUMBERS:
        return to_decimal(value)
    if field in DATES:
        return normalize_date(str(value))
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def _reference_period(text):
    """Infer date order from an unambiguous boundary in the labeled range."""
    dates = DATE_RE.findall(text)
    if len(dates) != 2:
        return []
    slash = [re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', date) for date in dates]
    day_first = any(match and int(match[1]) > 12 for match in slash)
    month_first = any(match and int(match[2]) > 12 for match in slash)
    if day_first and month_first:
        return []  # Conflicting label formats cannot supply a reliable reference.
    normalized = []
    for date, match in zip(dates, slash):
        if match and day_first:
            year = '%y' if len(match[3]) == 2 else '%Y'
            try:
                value = datetime.strptime(date.replace('-', '/'), '%d/%m/' + year).date().isoformat()
            except ValueError:
                return []
        else:
            value = normalize_date(date)
        if not value:
            return []
        normalized.append(value)
    return normalized if normalized[0] <= normalized[1] else []


def _reference(row):
    expected = {target: row[source] for source, target in REFERENCE_FIELDS.items()
                if row.get(source, '').strip()}
    items = []
    if row.get('items_json', '').strip():
        items = [{'description': item.get('description'), 'quantity': item.get('quantity'),
                  'unit_price': item.get('unit_price'), 'line_total': item.get('amount')}
                 for item in json.loads(row['items_json'])]
    elif row.get('line_items', '').strip():
        periods = []
        for part in row['line_items'].split(';'):
            tokens = [value.strip() for value in part.split('|')]
            if len(tokens) >= 4 and any('qty=' in value for value in tokens):
                numbers = dict(value.split('=', 1) for value in tokens[1:] if '=' in value)
                items.append({'description': tokens[0], 'quantity': numbers.get('qty'),
                              'unit_price': numbers.get('rate'), 'line_total': numbers.get('amount')})
            elif len(tokens) >= 4:
                items.append(dict(zip(('description', 'quantity', 'unit_price', 'line_total'), tokens[-4:])))
                if len(tokens) >= 5:
                    periods.extend(_reference_period(tokens[0]))
        if periods:
            expected.setdefault('service_start_date', min(periods))
            expected.setdefault('service_end_date', max(periods))
    return expected, items


def compare(row, result):
    expected, items = _reference(row)
    comparisons = []
    for field, truth in expected.items():
        wanted = _normalized(field, truth)
        if wanted is None:  # Unusable date/numeric labels are unknown, not perfect predictions.
            continue
        actual = getattr(result.invoice, field, None)
        comparisons.append({'field': field, 'expected': truth, 'actual': actual,
                            'correct': wanted == _normalized(field, actual)})
    if items:
        comparisons.append({'field': 'line_count', 'expected': len(items), 'actual': len(result.line_items),
                            'correct': len(items) == len(result.line_items)})
        for index, item in enumerate(items):
            actual_item = result.line_items[index].to_dict() if index < len(result.line_items) else {}
            for field, truth in item.items():
                if truth not in (None, ''):
                    actual = actual_item.get(field)
                    comparisons.append({'field': 'line_' + field, 'line': index + 1,
                                        'expected': truth, 'actual': actual,
                                        'correct': _normalized(field, truth) == _normalized(field, actual)})
    return comparisons


def _fingerprint(store):
    serialized = json.dumps([(batch_id, [asdict(result) for result in results])
                             for batch_id, results in store.load_batches()], sort_keys=True)
    files = sorted((store.root / 'models').glob('*'))
    catalog = store.vendor_catalog_folder()
    files.extend([catalog / 'vendor_accounts.csv', catalog / 'contracts.csv'])
    return {'history_sha256': hashlib.sha256(serialized.encode()).hexdigest(),
            'counts': store.count(),
            'training_sha256': hashlib.sha256(json.dumps(store.training_examples(), sort_keys=True).encode()).hexdigest(),
            'file_hashes': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in files if path.is_file()}}


def run(archives: list[Path], output: Path, workers: int = 4, predictions_from: Path | None = None):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    live = LocalStorage(settings.local_storage_dir)
    before = _fingerprint(live)
    accounts = live.vendor_accounts()
    entries, archive_checks, archive_hashes = [], [], {}
    for archive_path in archives:
        content = archive_path.read_bytes()
        archive_hashes[archive_path.name] = hashlib.sha256(content).hexdigest()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            _safe_archive_members(archive)
            references = {}
            if 'ground_truth_answer_sheet.csv' in archive.namelist():
                references = {row['source_file']: row for row in csv.DictReader(
                    io.StringIO(archive.read('ground_truth_answer_sheet.csv').decode('utf-8-sig')))}
            try:
                documents = expand_upload(archive_path.name, content, settings.max_file_mb * 1_000_000)
                archive_checks.append({'archive': archive_path.name, 'outcome': 'EXPANDED',
                                       'documents': len(documents), 'reason': ''})
            except ValueError as exc:
                # Evaluate large training corpora individually, not by relaxing UI ZIP limits.
                document_members = [member for member in archive.infolist()
                                    if Path(member.filename).suffix.lower() in SUPPORTED_EXTENSIONS]
                if len(document_members) <= MAX_ZIP_DOCUMENTS or 'more than' not in str(exc):
                    raise
                archive_checks.append({'archive': archive_path.name, 'outcome': 'UI_LIMIT_BLOCKED_AS_EXPECTED',
                                       'documents': len(document_members), 'reason': str(exc)})
                documents = [document for member in document_members for document in expand_upload(
                    Path(member.filename).name, archive.read(member), settings.max_file_mb * 1_000_000)]
            for document in documents:
                # Identical invoice/scan content may appear in multiple supplied archives.
                key = (document.filename, hashlib.sha256(document.data).hexdigest(),
                       document.intake_status, document.intake_message,
                       document.email_region, document.email_region_issue)
                entries.append({'archive': archive_path.name, 'document': document, 'key': key,
                                'reference': references.get(document.filename)})
    unique = {entry['key']: entry['document'] for entry in entries}
    predictions, timings = {}, {}
    def process(key, document):
        tick = time.monotonic()
        result = process_document(document, settings.default_tolerance, settings.minimum_field_confidence)
        return key, result, time.monotonic() - tick
    if predictions_from is not None:
        for cached in json.loads(predictions_from.read_text(encoding='utf-8')):
            key = tuple(cached['key'])
            if key in predictions:
                raise ValueError('Extraction checkpoint contains duplicate keys')
            predictions[key], timings[key] = _restore(cached['result']), cached['seconds']
        if predictions.keys() != unique.keys():
            raise ValueError('Extraction checkpoint does not match the supplied document bytes/context')
        print(f'Rebuilding reports from {len(predictions)} prior predictions; no new model inference', flush=True)
    else:
        _pilot()
        _reviewed_model()  # Warm only deployed app-owned artifacts; never train.
        print(f'Processing {len(unique)} unique inputs from {len(entries)} archive entries', flush=True)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process, key, document) for key, document in unique.items()]
            for index, future in enumerate(as_completed(futures), 1):
                key, result, elapsed = future.result()
                predictions[key], timings[key] = result, elapsed
                if index % 100 == 0 or index == len(unique):
                    print(f'Extracted {index}/{len(unique)}; elapsed {time.monotonic() - started:.1f}s', flush=True)
    (output / 'Predictions.json').write_text(json.dumps(
        [{'key': key, 'seconds': timings[key], 'result': asdict(result)}
         for key, result in predictions.items()], ensure_ascii=False), encoding='utf-8')
    # Detect genuine duplicate invoices on unique inputs, not repeated copies of the test archives.
    mark_duplicates(list(predictions.values()))
    records, comparisons, results = [], [], []
    for index, entry in enumerate(entries, 1):
        result = deepcopy(predictions[entry['key']])
        document = entry['document']
        result.source_email, result.source_attachment = document.source_email, document.source_attachment
        result.attachment_index = document.attachment_index
        row = mdm_row(result, accounts)
        scores = compare(entry['reference'], result) if entry['reference'] else []
        for score in scores:
            comparisons.append({'archive': entry['archive'], 'source': document.filename, **score})
        row.update({'Archive': entry['archive'], 'Entry': index,
                    'Final outcome': 'FAILED' if result.processing_status == 'FAILED' else row['Review status'],
                    'Reference comparisons': len(scores),
                    'Reference correct': sum(score['correct'] for score in scores),
                    'Reference mismatches': '; '.join(sorted({score['field'] for score in scores if not score['correct']})),
                    'Seconds': round(timings[entry['key']], 3)})
        records.append(row)
        results.append(result)
    counts = Counter(row['Final outcome'] for row in records)
    unique_counts = Counter('FAILED' if result.processing_status == 'FAILED' else
                            mdm_row(result, accounts)['Review status'] for result in predictions.values())
    field_scores = defaultdict(Counter)
    for score in comparisons:
        field_scores[score['field']]['tested'] += 1
        field_scores[score['field']]['correct'] += int(score['correct'])
    core_scores = [score for score in comparisons if score['field'] in CORE]
    core_accuracy = (round(100 * sum(score['correct'] for score in core_scores) / len(core_scores), 2)
                     if core_scores else None)
    all_accuracy = (round(100 * sum(score['correct'] for score in comparisons) / len(comparisons), 2)
                    if comparisons else None)
    checks = []
    if any(row['Review status'] == 'SUCCESS' and (not row['Billing Start Date'] or not row['Billing End Date'])
           for row in records):
        raise AssertionError('Success bypassed the mandatory service-date rule')
    checks.append('No missing-service-date invoice was marked Success')
    if any(row['Billing Account'] and not any(account.account == row['Billing Account']
           and account.vendor == row['Vendor -As per MDM'] for account in accounts) for row in records):
        raise AssertionError('Vendor or account does not come from the same master record')
    checks.append('All assigned vendor names and accounts come from the same master record')
    if before != _fingerprint(live):
        raise AssertionError('Live history, training, model, or master changed during this test')
    checks.append('Live invoice history, training examples, model artifacts, and masters unchanged')
    reports = {'Invoice_Results.csv': csv_bytes(records), 'Field_Comparisons.csv': csv_bytes(comparisons),
               'Archive_Intake_Checks.csv': csv_bytes(archive_checks),
               'Field_Scores.csv': csv_bytes([{'field': field, **score,
                                            'percent': round(100 * score['correct'] / score['tested'], 2)}
                                            for field, score in sorted(field_scores.items())]),
               'MDM/Invoice_data.csv': generate_mdm_csv(results, accounts),
               'MDM/Contract_verified_invoices.csv': generate_verified_csv(results, accounts)}
    for name, data in reports.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    print(f'CSV reports saved; writing Excel ({len(comparisons)} field comparisons)', flush=True)
    book = _excel_bytes(reports)
    (output / 'Invoice_Test_Results.xlsx').write_bytes(book)
    mdm_reader = csv.DictReader(io.StringIO(reports['MDM/Invoice_data.csv'].decode('utf-8-sig')))
    assert mdm_reader.fieldnames == COLUMNS and len(list(mdm_reader)) == len(results)
    verified = list(csv.DictReader(io.StringIO(reports['MDM/Contract_verified_invoices.csv'].decode('utf-8-sig'))))
    assert len(verified) == sum(row['Review status'] == 'SUCCESS' and row['Contract check status'] == 'PRESENT'
                                for row in records)
    checks.extend(['All records retained in the exact 18-column MDM report',
                   'Contract-verified export includes only eligible successful invoices'])
    summary = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'archive_hashes': archive_hashes,
               'run_mode': 'REPORT_REPLAY' if predictions_from else 'FRESH_EXTRACTION',
               'prediction_checkpoint': str(predictions_from) if predictions_from else '',
               'archive_entries': len(entries), 'unique_inputs': len(unique), 'status_counts': dict(counts),
               'unique_status_counts': dict(unique_counts), 'core_field_accuracy_percent': core_accuracy,
               'all_field_accuracy_percent': all_accuracy,
               'all_field_comparisons': len(comparisons),
               'processing_status_counts': dict(Counter(result.processing_status for result in results)),
               'core_field_comparisons': len(core_scores), 'field_scores': dict(field_scores),
               'verified_export_rows': len(verified), 'checks': checks,
               'seconds': round(time.monotonic() - started, 2),
               'note': 'Supplied synthetic/training-corpus regression, not independent company-invoice accuracy. '
                       'Blank reference labels are unknown and not scored. Repeated archive copies are included '
                       'in entry counts; unique-input counts are separate. No retraining or remote requests.'}
    if predictions_from:
        summary['note'] += ' Reports rebuilt from the identified prior extraction checkpoint; this is not a new model-inference run.'
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    reasons = Counter(row['Review reasons'] for row in records if row['Review status'] != 'SUCCESS')
    report = '\n'.join([
        '# Supplied Invoice Regression Report', '', f'Archive entries tested: {len(entries)}',
        f'Unique document/context inputs: {len(unique)}', f'Final outcomes: {dict(counts)}',
        f'Unique-input outcomes: {dict(unique_counts)}',
        f'All labeled fields normalized reference agreement: {all_accuracy}% ({len(comparisons)} comparisons)',
        f'Core field normalized reference agreement: {core_accuracy}% ({len(core_scores)} comparisons)',
        f'Eligible contract-verified export rows: {len(verified)}', '', summary['note'], '',
        '## Checks', '', *[f'- PASS: {check}' for check in checks], '',
        '## Field gaps', '', *[f"- {field}: {score['correct']}/{score['tested']} reference values matched"
                              for field, score in sorted(field_scores.items())
                              if score['correct'] < score['tested']], '',
        '## Archive intake', '', *[f"- {item['archive']}: {item['outcome']} ({item['documents']} documents). {item['reason']}"
                                  for item in archive_checks], '', '## Frequent non-success reasons', '',
        *[f'- {count}: {reason}' for reason, count in reasons.most_common(15)], '',
        '## Complete results', '', 'See Invoice_Results.csv and Invoice_Test_Results.xlsx for every entry; '
        'Field_Comparisons.csv contains expected and extracted values for every scored field.', '',
    ])
    (output / 'Invoice_Test_Report.md').write_text(report, encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key not in {'archive_hashes', 'field_scores'}}, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New, isolated report directory')
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--predictions-from', type=Path, help='Report-only replay of a prior JSON extraction checkpoint, not fresh inference')
    args = parser.parse_args()
    run(args.archives, args.output, args.workers, args.predictions_from)


if __name__ == '__main__':
    main()
