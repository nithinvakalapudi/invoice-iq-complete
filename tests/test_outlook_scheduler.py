"""Scheduled passes use temp storage and never connect to a real mailbox."""
import json
from dataclasses import replace

from models.invoice_schema import InvoiceResult
from services import outlook_scheduler
from services.outlook_folder import FolderRun


def test_scheduled_pass_writes_status_and_only_uses_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(outlook_scheduler, 'settings', replace(
        outlook_scheduler.settings, local_storage_dir=str(tmp_path),
        outlook_mailbox='person@example.com', outlook_invoice_folder='Invoices'))
    seen = []

    def run(storage, tolerance, threshold, max_bytes, **options):
        seen.append(options)
        return FolderRun(storage.outlook_folder, 'a' * 32, 2, 3, 0,
                         [InvoiceResult() for _ in range(4)], [], 2, 0,
                         'person@example.com')

    monkeypatch.setattr(outlook_scheduler, 'run_outlook_folder', run)
    assert outlook_scheduler.main() == 0
    assert seen == [{'source': 'desktop', 'mailbox': 'person@example.com',
                     'folder_name': 'Invoices'}]
    status = json.loads((tmp_path / 'outlook_schedule_status.json').read_text())
    assert status['outcome'] == 'completed'
    assert status['emails_processed'] == 2
    assert status['attachments_saved'] == 4


def test_scheduled_pass_records_error_for_later_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(outlook_scheduler, 'settings', replace(
        outlook_scheduler.settings, local_storage_dir=str(tmp_path)))

    def fail(*_args, **_kwargs):
        raise RuntimeError('Outlook is closed')

    monkeypatch.setattr(outlook_scheduler, 'run_outlook_folder', fail)
    assert outlook_scheduler.main() == 1
    status = json.loads((tmp_path / 'outlook_schedule_status.json').read_text())
    assert status['outcome'] == 'failed'
    assert 'Outlook is closed' in status['error']
