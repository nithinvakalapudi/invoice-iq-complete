# Offline invoice regression and benchmarks

## Supplied invoice archives

Run the deployed extractor against local invoice ZIPs without adding results to operational history:

```powershell
.venv\Scripts\python.exe -m evaluation.supplied_invoices "C:\Path\supplied.zip" --output evaluation_data\new-regression-run --workers 4
```

The output directory must be new. The runner processes actual PDF/image/email attachments, compares available answer-sheet fields and line items, applies service-date rejection and MDM rules, and produces full CSV/Excel reports with reasons. It does not retrain models, execute uploaded scripts, or make remote requests. It verifies that saved history, trained artifacts, and master files remain unchanged. For a training archive exceeding the UI's 200-document ZIP limit, individual documents are evaluated while the UI guard remains enforced.

Reports distinguish all-field agreement, core-field agreement, extraction completion, and business validation outcomes. A result on supplied training/synthetic data is not independent company-invoice accuracy; blank reference labels are unknown and are not scored.

## Historical public benchmark

Historical public benchmark files remain separate from operational invoice data. The current React interface does not show a Public dataset test results panel. Historical records are not current measured local-model accuracy.

The evaluation corpus comes from [Voxel51/high-quality-invoice-images-for-ocr](https://huggingface.co/datasets/Voxel51/high-quality-invoice-images-for-ocr), revision `d21f03cfeea2b330e15a229883c66d7ebece8e69`. Its synthetic annotations are not fully human-verified; blank labels are unknown, not confirmed absent. Images and prior results stay in ignored `evaluation_data`.

`python -m evaluation.benchmark prepare` can prepare the public dataset. The benchmark's automatic evaluation command is intentionally blocked until a validated local extractor is deployed, so it cannot create misleading failed-only runs. For the ten-invoice offline line-selection pilot, see [LOCAL_MODEL_PILOT_REPORT.md](../LOCAL_MODEL_PILOT_REPORT.md) and run `python -m training.local_pilot <corrected-invoices.zip>` after installing `requirements-local.txt`.

Do not equate model self-reported confidence or a synthetic dataset score with production accuracy. Validate against independent, reviewed company-like invoices and scans before enabling unattended processing.
