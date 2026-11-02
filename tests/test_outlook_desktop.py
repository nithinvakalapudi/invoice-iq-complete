"""Classic Outlook connector tests never touch the user's live mailbox."""
from dataclasses import replace

from fastapi.testclient import TestClient

import services.outlook_desktop as desktop
import services.outlook_folder as folder_service
import web_app
from models.invoice_schema import Invoice, InvoiceResult
from services.local_storage import LocalStorage
from utils.file_utils import DocumentInput


class Collection:
    def __init__(self, items):
        self.items = items
        self.Count = len(items)

    def Item(self, index):
        return self.items[index - 1]


class Attachment:
    def __init__(self, name, data, properties=None):
        self.FileName = name
        self.Size = len(data)
        self.data = data
        self.properties = properties or {}
        self.PropertyAccessor = self

    def GetProperty(self, key):
        if key not in self.properties:
            raise KeyError(key)
        return self.properties[key]

    def SaveAsFile(self, path):
        from pathlib import Path
        Path(path).write_bytes(self.data)


class Mail:
    Class = 43
    EntryID = 'entry-1'
    Subject = 'Invoice INV-1001 Region: APAC'
    Body = 'Attached invoice for Singapore'

    def __init__(self, attachments):
        self.Attachments = Collection(attachments)


class Folder:
    Name = 'Invoices'
    StoreID = 'store-1'

    def __init__(self, messages):
        self.Items = Collection(messages)


class Root:
    Name = 'person@example.com'

    def __init__(self, folder):
        self.Folders = Collection([folder])


def test_reads_only_real_attachments_and_uses_exact_mailbox(monkeypatch):
    hidden = Attachment('signature.png', b'image', {desktop._HIDDEN_PROPERTY: True})
    inline = Attachment('logo.jpg', b'image', {desktop._CID_PROPERTY: 'logo'})
    pdf = Attachment('invoice.pdf', b'%PDF-1.4 invoice')
    message = Mail([hidden, inline, pdf, Attachment('notes.txt', b'not invoice')])
    namespace = type('Namespace', (), {'Folders': Collection([Root(Folder([message]))])})()
    monkeypatch.setattr(desktop, '_mapi_namespace', lambda: namespace)
    read = desktop.read_invoice_emails('person@example.com', 'Invoices', 1000, lambda *_: False)
    assert read.mailbox == 'person@example.com'
    assert len(read.emails) == 1
    assert read.emails[0].attachments == [('invoice.pdf', b'%PDF-1.4 invoice')]
    assert read.emails[0].documents[0].source_attachment == 'invoice.pdf'
    assert read.emails[0].documents[0].email_region == 'APAC'
    assert desktop.read_invoice_emails('person@example.com', 'Invoices', 1000,
                                      lambda *_: True).already_processed == 1


def test_ambiguous_mailbox_requires_explicit_selection(monkeypatch):
    namespace = type('Namespace', (), {'Folders': Collection([
        Root(Folder([])), Root(Folder([]))])})()
    monkeypatch.setattr(desktop, '_mapi_namespace', lambda: namespace)
    try:
        desktop.read_invoice_emails('', 'Invoices', 1000, lambda *_: False)
    except RuntimeError as exc:
        assert 'OUTLOOK_MAILBOX' in str(exc)
    else:
        assert False, 'Expected ambiguous Outlook mailbox to be rejected'


def test_run_reads_desktop_mail_and_marks_read_after_persisting(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    labels = []
    marked = []

    def read(mailbox, folder_name, limit, processed, message_processed):
        identity = ('outlook:fake', 'digest-1')
        if processed(*identity):
            return desktop.DesktopRead([], 1, 0, [], 'person@example.com')
        source = 'Outlook/Invoice INV-1001 [123456789abc]'
        docs = [DocumentInput(name, b'%PDF-fake', source, name, index)
                for index, name in enumerate(('first.pdf', 'second.pdf'), 1)]
        return desktop.DesktopRead([
            desktop.DesktopEmail(identity, 'store', 'entry', source,
                                 [(d.filename, d.data) for d in docs], docs)
        ], 0, 0, [], 'person@example.com')

    def process(document, *_):
        labels.append(document.source_email)
        return InvoiceResult(invoice=Invoice(vendor_name='Vendor', invoice_number=document.filename,
                                            invoice_date='2026-10-01', currency='USD',
                                            total_amount='10.00'), source_file=document.filename,
                             source_email=document.source_email,
                             source_attachment=document.source_attachment,
                             processing_status='PROCESSED', validation_status='VALID')

    def mark(emails):
        assert LocalStorage(root).count() == (1, 2)
        marked.extend(email.entry_id for email in emails)
        return []

    monkeypatch.setattr(folder_service, 'read_invoice_emails', read)
    monkeypatch.setattr(folder_service, 'mark_emails_read', mark)
    monkeypatch.setattr(folder_service, 'process_document', process)
    client = TestClient(web_app.app)
    payload = {'tolerance': .02, 'threshold': 95, 'source': 'both'}
    first = client.post('/api/outlook/run', json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['desktop_emails_processed'] == 1
    assert first.json()['counts']['total'] == 2
    assert marked == ['entry']
    assert len(labels) == 2
    second = client.post('/api/outlook/run', json=payload)
    assert second.status_code == 200
    assert second.json()['emails_already_processed'] == 1
    assert second.json()['counts']['total'] == 0
    assert marked == ['entry']


def test_failed_attachment_is_not_marked_read(tmp_path, monkeypatch):
    root = tmp_path / 'local_data'
    monkeypatch.setattr(web_app, 'settings', replace(web_app.settings, local_storage_dir=str(root)))
    document = DocumentInput('broken.pdf', b'broken', 'Outlook/Invoice [1]', 'broken.pdf', 1)
    email = desktop.DesktopEmail(('outlook:bad', 'digest'), 'store', 'entry',
                                 document.source_email, [('broken.pdf', b'broken')], [document])
    monkeypatch.setattr(folder_service, 'read_invoice_emails', lambda *_:
                        desktop.DesktopRead([email], 0, 0, [], 'person@example.com'))
    marked = []
    monkeypatch.setattr(folder_service, 'mark_emails_read', lambda emails: marked.extend(emails) or [])
    result = TestClient(web_app.app).post('/api/outlook/run', json={
        'tolerance': .02, 'threshold': 95, 'source': 'desktop'})
    assert result.status_code == 200
    assert result.json()['counts']['failed'] == 1
    assert marked == []
    assert not LocalStorage(root).outlook_processed(*email.identity)


def test_mark_read_changes_only_the_committed_message(monkeypatch):
    class SavedMail:
        UnRead = True
        saved = False

        def Save(self):
            self.saved = True

    message = SavedMail()
    looked_up = []

    class Namespace:
        def GetItemFromID(self, entry_id, store_id):
            looked_up.append((entry_id, store_id))
            return message

    monkeypatch.setattr(desktop, '_mapi_namespace', lambda: Namespace())
    email = desktop.DesktopEmail(('outlook:key', 'digest'), 'store', 'entry',
                                 'Outlook/Invoice', [], [])
    assert desktop.mark_emails_read([email]) == []
    assert looked_up == [('entry', 'store')]
    assert message.UnRead is False
    assert message.saved is True


def test_processed_message_skips_attachment_download(monkeypatch):
    class DownloadForbidden(Attachment):
        def SaveAsFile(self, path):
            raise AssertionError('Already-saved Outlook attachment was downloaded again')

    message = Mail([DownloadForbidden('invoice.pdf', b'%PDF')])
    namespace = type('Namespace', (), {'Folders': Collection([Root(Folder([message]))])})()
    monkeypatch.setattr(desktop, '_mapi_namespace', lambda: namespace)
    result = desktop.read_invoice_emails('person@example.com', 'Invoices', 1000,
                                         lambda *_: False, lambda _: True)
    assert result.already_processed == 1
    assert result.emails == []
