"""Fill only missing currency/contract IDs from archived invoice documents.

Run without --apply for a read-only preview. Applying creates a SQLite backup
under uploads/_backups before touching saved rows; Reset removes that backup.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from config.settings import settings
from services.local_extraction_service import extract_invoice
from services.local_storage import LocalStorage
from services.vendor_matching import vendor_similarity


def _archived_document(store: LocalStorage, batch_id: str, result) -> Path | None:
    directory = store._batch_path(batch_id) / 'documents'
    manifest = directory / 'manifest.json'
    if not manifest.is_file():
        return None
    entries = json.loads(manifest.read_text(encoding='utf-8'))
    matches = [item for item in entries if item.get('original_filename') == result.source_file
               and item.get('source_email', '') == result.source_email
               and item.get('attachment_index') == result.attachment_index]
    if len(matches) != 1:
        return None
    path = directory / matches[0]['stored_filename']
    return path if path.is_file() and path.resolve().is_relative_to(directory.resolve()) else None


def run(store: LocalStorage, apply: bool = False) -> dict:
    accounts = store.vendor_accounts()
    counts = Counter()
    changes = []
    for batch_id, results in store.load_batches():
        changed = False
        for result in results:
            if result.processing_status in {'FAILED', 'SKIPPED'}:
                continue
            if result.invoice.currency and result.invoice.contract_id and result.invoice.vendor_name != 'Vendor':
                continue
            source = _archived_document(store, batch_id, result)
            if source is None:
                counts['source_unavailable'] += 1
                continue
            extracted = extract_invoice(source.read_bytes(), result.source_file)['invoice']
            counts['scanned'] += 1
            if not result.invoice.currency and extracted.get('currency'):
                result.invoice.currency = extracted['currency']
                result.errors = [error for error in result.errors if error != 'Missing required field: currency']
                counts['currency_filled'] += 1
                changed = True
            if not result.invoice.contract_id and extracted.get('contract_id'):
                result.invoice.contract_id = extracted['contract_id']
                counts['contract_id_filled'] += 1
                changed = True
            if result.invoice.vendor_name == 'Vendor' and extracted.get('vendor_name'):
                # This repairs a placeholder vendor using an independently
                # printed contract ID. Billing Account matching still requires
                # invoice Region to match the MDM Restricted To value.
                confirmed = [account for account in accounts
                             if result.invoice.contract_id
                             and account.account.casefold() == result.invoice.contract_id.casefold()
                             and vendor_similarity(extracted['vendor_name'], account.vendor) >= 70]
                if confirmed:
                    result.invoice.vendor_name = extracted['vendor_name']
                    result.errors = [error for error in result.errors
                                     if error != 'Missing required field: vendor_name']
                    counts['vendor_placeholder_corrected'] += 1
                    changed = True
        if changed:
            changes.append((batch_id, results))
    counts['batches_to_update'] = len(changes)
    if apply and changes:
        backup_dir = store.root / 'uploads' / '_backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f'invoice_history_before_field_backfill_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sqlite3'
        with sqlite3.connect(store.database) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        for batch_id, results in changes:
            warnings = store.save_batch(batch_id, results)
            if warnings:
                counts['export_warnings'] += len(warnings)
        counts['backup_created'] = 1
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and update saved invoice history')
    args = parser.parse_args()
    print(json.dumps(run(LocalStorage(settings.local_storage_dir), args.apply), indent=2))


if __name__ == '__main__':
    main()
