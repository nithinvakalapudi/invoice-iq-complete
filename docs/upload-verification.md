# Upload and workflow verification — 1 November 2026

Tests use the real FastAPI routes with a temporary database, source archive,
output folder and synthetic MDM masters. Live invoice history is not modified.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe -m evaluation.upload_smoke
```

The batch contains five seeded-random Kaggle images outside the earlier
60-image sample, three synthetic PDFs, one rendered/scanned image and one
synthetic email with two PDF attachments: 11 resulting invoices in total.

## Observed outcomes

- Upload, Run MDM, Check and CSV download routes returned HTTP 200.
- All 11 resulting invoices were returned; none had processing status FAILED.
- One complete PDF, one scanned invoice and the valid email attachment passed
  validation and entered the successful invoice CSV.
- The five Kaggle invoices and two synthetic missing-date invoices were
  rejected under the existing missing-service-date policy. The dataset images
  do not print service periods; this is not an extraction crash.
- The invoice with distinct service periods required review instead of taking
  its first date range.
- Re-uploading the valid invoice flagged a possible duplicate.
- Replacing its synthetic contract with an expired one rejected the formerly
  valid invoices and removed them from the successful export.
- On the five random images, supplier, customer, invoice number, total and tax
  matched the labels on all 25 comparisons. All five printed invoice-date
  strings are now retained, including 03/08 and 11/07; their calendar order
  is not guessed merely to calculate ageing.

The expanded checker also verifies the complete expected field values for
the three successful synthetic documents. Results and per-invoice values are
saved to ignored `evaluation_data/upload_smoke/report.json`.
The final OCR/rules-only run passed every workflow check and had no checked
value mismatches. All dates were retained as printed. The full Python suite
passed 325 tests. No trained invoice model or model service was used.

## Defects found and addressed

- A clearly labelled invoice reference containing letters but no digits was
  discarded. Explicit references are now retained with heading checks.
- A model-ranked street address could populate Bank Account Number. That
  field now requires an explicit printed account label.
- Supplier city/country lines without postal digits were ignored. They now
  remain eligible, confined to the supplier block before Bill To.
- Space grouping and decimal commas in annotations produced false amount
  mismatches. The comparison now normalizes both numeric representations.
- A Value Added Tax table row could confuse its quantity or tax percentage
  with tax money. Spatial reading now associates it with the amount column.

## What this does not verify

This test uses saved email-file intake, not live Classic Outlook COM access.
The four original business invoices shown in photographs are still unavailable
as source attachments. This sample does not establish universal layout coverage.
