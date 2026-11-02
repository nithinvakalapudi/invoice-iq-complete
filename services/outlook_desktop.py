"""Read invoice attachments from the signed-in classic Outlook desktop profile.

This uses Outlook's local MAPI object model. No Graph credentials, add-in, or
mailbox rule is required. The caller owns persistence and read-state changes.
"""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from services.email_region import email_region
from utils.file_utils import DocumentInput, is_supported

_MAIL_CLASS = 43
_HIDDEN_PROPERTY = 'http://schemas.microsoft.com/mapi/proptag/0x7FFE000B'
_CID_PROPERTY = 'http://schemas.microsoft.com/mapi/proptag/0x3712001F'
_LOCATION_PROPERTY = 'http://schemas.microsoft.com/mapi/proptag/0x3713001F'


@dataclass
class DesktopEmail:
    identity: tuple[str, str]
    store_id: str
    entry_id: str
    source_label: str
    attachments: list[tuple[str, bytes]]
    documents: list[DocumentInput]


@dataclass
class DesktopRead:
    emails: list[DesktopEmail]
    already_processed: int
    ignored: int
    warnings: list[str]
    mailbox: str
    scanned_messages: int = 0


def _mapi_namespace():
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError('Classic Outlook integration requires pywin32 on Windows.') from exc
    try:
        return win32com.client.GetActiveObject('Outlook.Application').GetNamespace('MAPI')
    except Exception as exc:
        raise RuntimeError('Classic Outlook is not running or its local profile is unavailable.') from exc


def _invoice_folder(namespace, mailbox: str, folder_name: str):
    if not folder_name or '/' in folder_name or '\\' in folder_name:
        raise ValueError('Outlook invoice folder must be one folder name.')
    matches = []
    for index in range(1, namespace.Folders.Count + 1):
        root = namespace.Folders.Item(index)
        if mailbox and str(root.Name).casefold() != mailbox.casefold():
            continue
        for child_index in range(1, root.Folders.Count + 1):
            child = root.Folders.Item(child_index)
            if str(child.Name).casefold() == folder_name.casefold():
                matches.append((str(root.Name), child))
    if len(matches) > 1:
        raise RuntimeError('More than one Outlook mailbox has this invoice folder. Set OUTLOOK_MAILBOX in .env.')
    if not matches:
        target = f" in mailbox '{mailbox}'" if mailbox else ''
        raise RuntimeError(f"Outlook folder '{folder_name}' was not found{target}.")
    return matches[0]


def _property(attachment, name: str):
    try:
        return attachment.PropertyAccessor.GetProperty(name)
    except Exception:
        return None


def _source_label(subject: str, entry_id: str) -> str:
    clean = ' '.join(str(subject or 'No subject').split())[:120]
    digest = hashlib.sha256(entry_id.encode('utf-8')).hexdigest()[:12]
    return f'Outlook/{clean} [{digest}]'


def read_invoice_emails(mailbox: str, folder_name: str, max_file_bytes: int,
                        already_processed: Callable[[str, str], bool],
                        message_processed: Callable[[str], bool] | None = None,
                        max_new_emails: int = 100) -> DesktopRead:
    """Copy supported, non-inline attachments; never mutate the mailbox."""
    try:
        import pythoncom
    except ImportError as exc:
        raise RuntimeError('Classic Outlook integration requires pywin32 on Windows.') from exc
    pythoncom.CoInitialize()
    try:
        namespace = _mapi_namespace()
        mailbox_name, folder = _invoice_folder(namespace, mailbox, folder_name)
        store_id = str(folder.StoreID)
        emails: list[DesktopEmail] = []
        warnings: list[str] = []
        skipped = ignored = 0
        items = folder.Items
        # Snapshot the actual COM objects before doing attachment work. Avoid
        # iterating the live collection or resolving each EntryID again: Outlook
        # may reorder Items during sync, and GetItemFromID can fail for items
        # surfaced through delegated or secondary stores.
        item_count = int(items.Count)
        item_snapshot = []
        for item_index in range(1, item_count + 1):
            try:
                candidate = items.Item(item_index)
                if int(candidate.Class) == _MAIL_CLASS and candidate.EntryID:
                    item_snapshot.append(candidate)
            except Exception as exc:
                warnings.append(f'Outlook item {item_index}: could not enumerate message: {exc}.')
        for item_index, message in enumerate(item_snapshot, 1):
            if len(emails) >= max_new_emails:
                warnings.append(f'Run limited to {max_new_emails} new Outlook emails; select Run again for the rest.')
                break
            try:
                entry_id = str(message.EntryID)
                label = _source_label(message.Subject, entry_id)
                message_key = 'outlook:' + hashlib.sha256((store_id + entry_id).encode()).hexdigest()
                if message_processed and message_processed(message_key):
                    skipped += 1
                    warnings.append(f'{label}: this Outlook email was already processed; skipped.')
                    continue
                attachment_count = int(message.Attachments.Count)
                if attachment_count > 200:
                    warnings.append(f'{label}: more than 200 attachments; email skipped.')
                    continue
                attachments: list[tuple[str, bytes]] = []
                documents: list[DocumentInput] = []
                region, region_issue = email_region(str(message.Subject or ''),
                                                    str(message.Body or '')[:32000])
                with tempfile.TemporaryDirectory(prefix='invoice-outlook-') as temp:
                    for attach_index in range(1, attachment_count + 1):
                        attachment = message.Attachments.Item(attach_index)
                        if (_property(attachment, _HIDDEN_PROPERTY) or
                            _property(attachment, _CID_PROPERTY) or
                            _property(attachment, _LOCATION_PROPERTY)):
                            continue
                        original = str(attachment.FileName or f'attachment-{attach_index}')
                        name = PurePosixPath(original.replace('\\', '/')).name
                        if not is_supported(name):
                            continue
                        if int(attachment.Size) > max_file_bytes:
                            raise ValueError(f'{name} exceeds the document size limit.')
                        target = Path(temp) / f'attachment-{attach_index}{Path(name).suffix.lower()}'
                        attachment.SaveAsFile(str(target))
                        if target.stat().st_size > max_file_bytes:
                            raise ValueError(f'{name} exceeds the document size limit.')
                        data = target.read_bytes()
                        if not data:
                            raise ValueError(f'{name} has no readable file content.')
                        attachments.append((name, data))
                        documents.append(DocumentInput(
                            name, data, label, name, attach_index,
                            email_region=region, email_region_issue=region_issue))
                if not documents:
                    ignored += 1
                    warnings.append(f'{label}: no supported invoice attachments found; supported types are PDF, common image files, CSV, XLSX, EML and MSG.')
                    continue
                digest = hashlib.sha256()
                for document in documents:
                    digest.update(document.attachment_index.to_bytes(4, 'big'))
                    digest.update(document.filename.encode('utf-8'))
                    digest.update(document.data)
                identity = (message_key, digest.hexdigest())
                if already_processed(*identity):
                    skipped += 1
                    warnings.append(f'{label}: attachment contents were already processed; skipped as duplicate intake.')
                    continue
                emails.append(DesktopEmail(identity, store_id, entry_id, label, attachments, documents))
            except Exception as exc:
                warnings.append(f'Outlook item {item_index}: {exc}. It was not processed.')
        return DesktopRead(emails, skipped, ignored, warnings, mailbox_name, len(item_snapshot))
    finally:
        pythoncom.CoUninitialize()


def mark_emails_read(emails: list[DesktopEmail]) -> list[str]:
    """Mark only emails already committed to local history as read."""
    if not emails:
        return []
    import pythoncom
    pythoncom.CoInitialize()
    try:
        namespace = _mapi_namespace()
        warnings = []
        for email in emails:
            try:
                message = namespace.GetItemFromID(email.entry_id, email.store_id)
                if message.UnRead:
                    message.UnRead = False
                    message.Save()
            except Exception as exc:
                warnings.append(f'{email.source_label}: saved locally, but Outlook could not mark it read: {exc}')
        return warnings
    finally:
        pythoncom.CoUninitialize()
