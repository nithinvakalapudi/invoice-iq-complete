from uuid import uuid4

from models.invoice_schema import Invoice, InvoiceResult
from services.local_storage import LocalStorage
from training import backfill_saved_currency_contract as backfill
from utils.file_utils import DocumentInput


def test_backfill_previews_then_updates_only_missing_fields(tmp_path, monkeypatch):
    store = LocalStorage(tmp_path / 'local_data')
    catalog = store.root / 'MDM' / 'vendor_accounts.csv'
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_text('Account,Vendor,Restricted To\nCON-001,Pinnacle Analytics,APAC\n', encoding='utf-8')
    (catalog.parent / 'contracts.csv').write_text(
        'Contract ID,Vendor\nCON-001,Pinnacle Analytics\n', encoding='utf-8')
    batch_id = uuid4().hex
    store.archive_documents(batch_id, [DocumentInput('invoice.pdf', b'%PDF-archived')])
    original = InvoiceResult(invoice=Invoice(vendor_name='Vendor', invoice_number='INV-1',
                                            invoice_date='2026-10-01', total_amount='100'),
                             source_file='invoice.pdf', errors=['Missing required field: currency'],
                             processing_status='LOCAL_DRAFT')
    store.save_batch(batch_id, [original])
    monkeypatch.setattr(backfill, 'extract_invoice', lambda *_: {'invoice': {
        'vendor_name': 'Pinnacle Analytics', 'currency': 'USD', 'contract_id': 'CON-001'}})
    preview = backfill.run(store)
    assert preview['currency_filled'] == preview['contract_id_filled'] == 1
    assert store.load_batches()[0][1][0].invoice.currency is None
    applied = backfill.run(store, apply=True)
    assert applied['backup_created'] == 1
    saved = store.load_batches()[0][1][0]
    assert saved.invoice.currency == 'USD'
    assert saved.invoice.contract_id == 'CON-001'
    assert saved.invoice.vendor_name == 'Pinnacle Analytics'
    assert saved.invoice.invoice_number == 'INV-1'
    assert saved.validation_status == original.validation_status
    assert 'Missing required field: currency' not in saved.errors
    assert list((store.root / 'uploads' / '_backups').glob('*.sqlite3'))
