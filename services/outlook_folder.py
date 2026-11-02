"""Manual, local-folder email intake through the existing invoice pipeline."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from models.invoice_schema import InvoiceResult
from services.document_processing import process_document
from services.duplicate_service import mark_duplicates
from services.local_storage import LocalStorage
from services.outlook_desktop import DesktopEmail, mark_emails_read, read_invoice_emails
from services.storage_lock import exclusive_folder_operation
from utils.file_utils import expand_upload

_RUN_LOCK = Lock()


@dataclass
class FolderRun:
    folder: Path
    batch_id: str | None
    emails_processed: int
    emails_already_processed: int
    ignored_files: int
    results: list[InvoiceResult]
    warnings: list[str]
    desktop_emails_processed: int = 0
    local_emails_processed: int = 0
    outlook_mailbox: str = ''
    desktop_messages_scanned: int = 0


@exclusive_folder_operation
def run_outlook_folder(storage: LocalStorage, tolerance: float, threshold: float,
                       max_file_bytes: int, source: str = 'local',
                       mailbox: str = '', folder_name: str = 'Invoices') -> FolderRun:
    """Process local email files and/or a classic Outlook Invoices folder."""
    if source not in {'local', 'desktop', 'both'}:
        raise ValueError('Outlook source must be local, desktop, or both.')
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError('An Outlook folder run is already in progress.')
    try:
        folder = storage.outlook_folder
        uploads: list[tuple[str, bytes]] = []
        identities: list[tuple[str, str]] = []
        skipped = ignored = 0
        intake_warnings = []
        local_count = 0
        if source in {'local', 'both'}:
            for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
                if path.suffix.casefold() not in {'.msg', '.eml'} or not path.is_file():
                    ignored += 1
                    continue
                try:
                    if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(folder):
                        raise ValueError('Linked Outlook files are not supported.')
                    before = path.stat()
                    if before.st_size > max_file_bytes:
                        raise ValueError(f'Email exceeds the {max_file_bytes / 1_000_000:g} MB limit.')
                    with path.open('rb') as stream:
                        data = stream.read(max_file_bytes + 1)
                    after = path.stat()
                    if len(data) > max_file_bytes:
                        raise ValueError('Email grew beyond the upload size limit.')
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError('Email is still changing; finish copying it and select Run again.')
                except (OSError, ValueError) as exc:
                    intake_warnings.append(f'{path.name}: {exc} This email was not processed; other emails continue.')
                    continue
                digest = hashlib.sha256(data).hexdigest()
                if storage.outlook_processed(path.name, digest):
                    skipped += 1
                    continue
                uploads.append((path.name, data))
                identities.append((path.name, digest))
                local_count += 1
        desktop_emails: list[DesktopEmail] = []
        outlook_mailbox = ''
        desktop_messages_scanned = 0
        if source in {'desktop', 'both'}:
            try:
                desktop = read_invoice_emails(mailbox, folder_name, max_file_bytes,
                                              storage.outlook_processed,
                                              storage.outlook_message_processed)
                desktop_emails = desktop.emails
                outlook_mailbox = desktop.mailbox
                desktop_messages_scanned = desktop.scanned_messages
                skipped += desktop.already_processed
                ignored += desktop.ignored
                intake_warnings.extend(desktop.warnings)
            except (OSError, ValueError, RuntimeError) as exc:
                if source == 'desktop':
                    raise
                intake_warnings.append(f'Classic Outlook unavailable: {exc} Local email files were still checked.')
        if not uploads and not desktop_emails:
            return FolderRun(folder, None, 0, skipped, ignored, [],
                             intake_warnings + storage.export_warnings(), 0, 0, outlook_mailbox,
                             desktop_messages_scanned)

        batch_id = uuid4().hex
        documents = []
        results = []
        for name, data in uploads:
            try:
                documents.extend(expand_upload(name, data, max_file_bytes))
            except ValueError as exc:
                failure = InvoiceResult.failed(name, str(exc), datetime.now(timezone.utc).isoformat())
                failure.source_email = name
                results.append(failure)
        for email in desktop_emails:
            uploads.extend(email.attachments)
            documents.extend(email.documents)
        storage.archive_uploads(batch_id, uploads)
        storage.archive_documents(batch_id, documents)
        results.extend(process_document(document, tolerance, threshold) for document in documents)
        for result in results:
            result.mdm_checked = False
        prior_results = [prior for _, batch_results in storage.load_batches() for prior in batch_results]
        mark_duplicates(results, prior_results)
        complete_emails = [email for email in desktop_emails
                           if all(result.processing_status != 'FAILED' for result in results
                                  if result.source_email == email.source_label)]
        identities.extend(email.identity for email in complete_emails)
        warnings = intake_warnings + storage.save_batch(batch_id, results, outlook_files=identities)
        warnings.extend(mark_emails_read(complete_emails))
        return FolderRun(folder, batch_id, local_count + len(desktop_emails), skipped, ignored,
                         results, warnings, len(desktop_emails), local_count, outlook_mailbox,
                         desktop_messages_scanned)
    finally:
        _RUN_LOCK.release()
