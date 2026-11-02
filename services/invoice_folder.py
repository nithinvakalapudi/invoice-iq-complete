"""Explicit local folder runs. Originals are read-only, never moved or deleted."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from models.invoice_schema import InvoiceResult
from services.duplicate_service import mark_duplicates
from services.storage_lock import exclusive_folder_operation
from utils.file_utils import EMAIL_EXTENSIONS, SUPPORTED_EXTENSIONS, expand_upload

SUPPORTED_INPUTS = SUPPORTED_EXTENSIONS | EMAIL_EXTENSIONS | {'.zip', '.csv', '.xlsx'}


def extract_uploads(uploads, tolerance, threshold, max_bytes, processor, importer):
    documents, results, completed = [], [], set()
    for name, data in uploads:
        source_results = []
        try:
            if Path(name).suffix.casefold() in {'.csv', '.xlsx'}:
                source_results = importer(name, data, tolerance, threshold)
            else:
                source_documents = expand_upload(name, data, max_bytes)
                documents.extend(source_documents)
                source_results = [processor(document, tolerance, threshold) for document in source_documents]
        except ValueError as exc:
            failure = InvoiceResult.failed(name, str(exc), datetime.now(timezone.utc).isoformat())
            if Path(name).suffix.casefold() in EMAIL_EXTENSIONS:
                failure.source_email = name
            source_results = [failure]
        results.extend(source_results)
        if source_results and all(result.processing_status != 'FAILED' for result in source_results):
            completed.add(name)
    return documents, results, completed


def save_upload_batch(store, uploads, tolerance, threshold, max_bytes, processor, importer,
                      identities=None):
    batch_id = uuid4().hex
    documents, results, completed = extract_uploads(uploads, tolerance, threshold, max_bytes, processor, importer)
    for result in results:
        result.mdm_checked = False
    store.archive_uploads(batch_id, uploads)
    store.archive_documents(batch_id, documents)
    prior = [record for _, records in store.load_batches() for record in records]
    mark_duplicates(results, prior)
    # Failed-only files remain retryable. Skipped containers do not fabricate an
    # invoice, but are remembered so repeated Run does not append them forever.
    committed = [(key, digest) for name, key, digest in identities or [] if name in completed]
    warnings = store.save_batch(batch_id, results, outlook_files=committed)
    return batch_id, results, warnings


@exclusive_folder_operation
def run_invoice_folder(store, folder, tolerance, threshold, max_bytes, processor, importer):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError('Invoice input folder does not exist. Update Settings.')
    uploads, identities, warnings = [], [], []
    already = ignored = 0
    # Deliberately non-recursive, limited to the same 100 sources as manual upload.
    for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if path.suffix.casefold() not in SUPPORTED_INPUTS or not path.is_file():
            ignored += 1
            continue
        try:
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(folder):
                raise ValueError('Linked input files are not supported.')
            before = path.stat()
            if before.st_size > max_bytes:
                raise ValueError('File exceeds the upload size limit.')
            with path.open('rb') as stream:
                payload = stream.read(max_bytes + 1)
            after = path.stat()
            if len(payload) > max_bytes or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('File is still changing. Finish copying it and Run again.')
            digest = hashlib.sha256(payload).hexdigest()
            key = 'input-folder:' + str(path)
            if store.outlook_processed(key, digest):
                already += 1
                continue
            if len(uploads) == 100:
                warnings.append('Processed at most 100 new files. Run again for remaining files.')
                break
            uploads.append((path.name, payload))
            identities.append((path.name, key, digest))
        except (OSError, ValueError) as exc:
            warnings.append(f'{path.name}: {exc}')
    if not uploads:
        return None, [], warnings, already, ignored
    # Source associations and skip identities are committed with the single batch.
    batch_id, results, saved_warnings = save_upload_batch(
        store, uploads, tolerance, threshold, max_bytes, processor, importer, identities)
    return batch_id, results, warnings + saved_warnings, already, ignored
