"""Download, evaluate and optionally train from labelled Kaggle invoice images.

The image holdout is excluded from model fitting. This dataset does not label
service dates, regions or MDM eligibility, and cannot evaluate those fields.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import joblib
import sklearn

from services import local_extraction_service as extraction
from services.ocr_service import extract_document_text
from training.local_pilot import FIELDS, _fit_field, _exact_match
from services.local_storage import _atomic_write

DATASET = 'osamahosamabdellatif/high-quality-invoice-images-for-ocr'
BASE = 'https://www.kaggle.com/api/v1/datasets/download/' + DATASET + '?fileName='


def download(member: str, destination: Path):
    if not destination.is_file():
        with urlopen(BASE + quote(member, safe=''), timeout=60) as response:
            payload = response.read()
        if payload.lstrip().startswith(b'<'):
            raise ValueError('Kaggle returned HTML rather than the requested dataset file')
        _atomic_write(destination, payload)
    return destination


def run(root: Path, limit: int, train: bool):
    label_path = download('batch_1/batch_1/batch1_1.csv', root / 'labels.csv')
    with label_path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    rows.sort(key=lambda row: hashlib.sha256(row['File Name'].encode()).hexdigest())
    rows = rows[:limit]

    def prepare(row):
        filename = Path(row['File Name']).name
        path = download('batch_1/batch_1/batch1_1/' + filename, root / 'images' / filename)
        text_path = root / 'ocr' / (filename + '.txt')
        if not text_path.is_file():
            _atomic_write(text_path, extract_document_text(filename, path.read_bytes()).encode())
        text = text_path.read_text(encoding='utf-8')
        label = json.loads(row['Json Data'])
        invoice, totals = label.get('invoice', {}), label.get('subtotal', {})
        gold = {field: '' for field in FIELDS}
        gold.update(vendor_name=invoice.get('seller_name', ''),
                    customer_name=invoice.get('client_name', ''),
                    invoice_number=invoice.get('invoice_number', ''),
                    invoice_date=invoice.get('invoice_date', ''),
                    total_amount=totals.get('total', ''), tax_amount=totals.get('tax', ''))
        return path, gold, [line.strip() for line in text.splitlines() if line.strip()]

    # OCR itself runs separately in Tesseract subprocesses; keep parallelism small.
    with ThreadPoolExecutor(max_workers=3) as pool:
        examples = list(pool.map(prepare, rows))
    if len(examples) < 10:
        raise ValueError('Use at least 10 invoices for a separate training/holdout split')
    holdout = examples[::5]
    fitting = [example for index, example in enumerate(examples) if index % 5]
    fields = ('vendor_name', 'customer_name', 'invoice_number', 'invoice_date', 'total_amount', 'tax_amount')
    models = {}
    if train:
        for field in fields:
            fitted, _ = _fit_field([(gold, lines) for _, gold, lines in fitting], field)
            if fitted is not None:
                models[field] = fitted

    def measure(use_new):
        original = extraction._reviewed_model
        if use_new:
            from training.local_pilot import _features
            extraction._reviewed_model = lambda: (models, _features)
        scores = {field: {'correct': 0, 'tested': 0} for field in fields}
        records = []
        try:
            for path, gold, _ in holdout:
                payload = extraction.extract_invoice(path.read_bytes(), path.name)
                actual = payload['invoice']
                for field in fields:
                    if gold[field]:
                        scores[field]['tested'] += 1
                        scores[field]['correct'] += int(_exact_match(str(gold[field]), actual.get(field), field))
                records.append({'file': path.name, 'expected': gold, 'actual': actual,
                                'issues': payload.get('_extraction_issues', [])})
        finally:
            extraction._reviewed_model = original
        return {'fields': scores, 'records': records}

    report = {'dataset': DATASET, 'label_sha256': hashlib.sha256(label_path.read_bytes()).hexdigest(),
              'total_images': len(examples), 'training_images': len(fitting), 'holdout_images': len(holdout),
              'scope': 'One batch, limited sample; not a business-invoice accuracy claim',
              'unsupported_labels': ['service_start_date', 'service_end_date', 'region', 'billing_account', 'contract'],
              'baseline': measure(False)}
    if train:
        report['candidate'] = measure(True)
        artifact = root / 'candidate_model.joblib'
        joblib.dump({'version': 1, 'models': models, 'metadata': {
            'sklearn_version': sklearn.__version__, 'dataset': DATASET,
            'training_files': [path.name for path, _, _ in fitting],
            'holdout_files': [path.name for path, _, _ in holdout]}}, artifact)
        report['candidate_model'] = str(artifact)
        report['deployment'] = 'Candidate only; existing production model was not overwritten'
    _atomic_write(root / 'evaluation.json', json.dumps(report, indent=2).encode())
    return {key: value for key, value in report.items() if key not in {'baseline', 'candidate'}} | {
        key: report[key]['fields'] for key in ('baseline', 'candidate') if key in report}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('evaluation_data/kaggle_sample'))
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--train', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.limit, args.train), indent=2))
