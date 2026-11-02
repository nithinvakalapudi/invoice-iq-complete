# Supplied Invoice Regression Report

## Application verification

- Backend: 274 tests passed.
- Frontend: 11 tests passed; production build succeeded.
- Application responding at http://127.0.0.1:8505/.
- Fixed a large Excel-export scaling issue: the exporter now addresses each new row directly instead of repeatedly scanning earlier worksheet rows. Regression tests retain numeric formats, account leading zeros, and formula-injection protection.
- Existing operational history remains 1 batch / 9 invoices, all approved by the current checks, with no export warnings. These regression results were not appended to live invoice history.

## Real-file outcome

Archive entries tested: 2176
Unique document/context inputs: 2102
Final outcomes: {'REVIEW_REQUIRED': 22, 'REJECTED': 2152, 'FAILED': 2}
Unique-input outcomes: {'REVIEW_REQUIRED': 22, 'REJECTED': 2078, 'FAILED': 2}
All labeled fields normalized reference agreement: 82.52% (66632 comparisons)
Core field normalized reference agreement: 99.99% (14788 comparisons)
Eligible contract-verified export rows: 0

Success count: 0. Rejected entries lack a required service-date boundary. Review entries include missing invoice dates, duplicate invoice references, and missing or ambiguous MDM mappings. The 2 failed inputs are Blue_Ocean_Invoice_Mail_01.msg and Blue_Ocean_Invoice_Mail_02.msg: both contain only a properties stream, without email content or attachments. They must be re-exported from the original Outlook emails; missing attachments cannot be recovered from these containers.

The current master matched 12 entries; 2,158 had no vendor match and 6 were ambiguous. The matched vendor name and Billing Account were always taken from the same authoritative master record. No new accounts were invented or inserted into the master.

Supplied synthetic/training-corpus regression, not independent company-invoice accuracy. Blank reference labels are unknown and not scored. Repeated archive copies are included in entry counts; unique-input counts are separate. No retraining or remote requests. Reports rebuilt from the identified prior extraction checkpoint; this is not a new model-inference run.

## Checks

- PASS: No missing-service-date invoice was marked Success
- PASS: All assigned vendor names and accounts come from the same master record
- PASS: Live invoice history, training examples, model artifacts, and masters unchanged
- PASS: All records retained in the exact 18-column MDM report
- PASS: Contract-verified export includes only eligible successful invoices

## Field gaps

- customer_address: 0/2110 reference values matched
- discount: 0/2000 reference values matched
- invoice_date: 2108/2110 reference values matched
- line_count: 2010/2110 reference values matched
- line_description: 7939/8271 reference values matched
- line_line_total: 7939/8271 reference values matched
- line_quantity: 7939/8271 reference values matched
- line_unit_price: 7939/8271 reference values matched
- payment_terms: 0/2000 reference values matched
- shipping_amount: 0/2000 reference values matched
- vendor_address: 0/2110 reference values matched

## Archive intake

- invoices_10_unique.zip: EXPANDED (10 documents). 
- invoices_training_corrected.zip: EXPANDED (16 documents). 
- invoice_training_50.zip: EXPANDED (70 documents). 
- invoice_training_50 (1).zip: EXPANDED (70 documents). 
- invoice_2000_training_dataset.zip: UI_LIMIT_BLOCKED_AS_EXPECTED (2000 documents). ZIP contains more than 200 supported documents: invoice_2000_training_dataset.zip
- two_outlook_invoice_emails.zip: EXPANDED (8 documents). 
- outlook_invoice_mails_like_reference.zip: EXPANDED (2 documents). 

## Frequent non-success reasons

- 1649: Missing required: Billing Start Date, Billing End Date; Total mismatch: subtotal + tax + shipping - discount does not equal total; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Billing Account: No sufficiently similar MDM vendor; Local extraction has no calibrated field confidence; verify against the invoice
- 465: Missing required: Billing Start Date, Billing End Date; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Billing Account: No sufficiently similar MDM vendor; Local extraction has no calibrated field confidence; verify against the invoice
- 15: Missing required: Billing Start Date, Billing End Date; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Billing Account: No sufficiently similar MDM vendor; Possible duplicate invoice
- 13: Billing Account: No sufficiently similar MDM vendor; Possible duplicate invoice
- 10: Missing required: Billing Start Date, Billing End Date; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Local extraction has no calibrated field confidence; verify against the invoice
- 8: Missing required: Vendor, Billing Start Date, Billing End Date; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Billing Account: Invoice vendor is blank; Local extraction has no calibrated field confidence; verify against the invoice
- 4: Missing required: Invoice Date; Billing Account: No sufficiently similar MDM vendor; Local extraction has no calibrated field confidence; verify against the invoice
- 4: Missing required: Billing Start Date, Billing End Date; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Billing Account: Multiple MDM accounts match the vendor; no invoice or email Region is available; Possible duplicate invoice
- 2: Possible duplicate invoice
- 1: Missing required: Billing Start Date, Billing End Date; Line-item total does not equal subtotal; Invoice rejected: missing Service Date (Billing Start Date, Billing End Date); Billing Account: No sufficiently similar MDM vendor; Possible duplicate invoice
- 1: Billing Account: No sufficiently similar MDM vendor
- 1: Billing Account: Multiple MDM accounts match the vendor; no invoice or email Region is available
- 1: Line-item total does not equal subtotal; Billing Account: Multiple MDM accounts match the vendor; no invoice or email Region is available; Possible duplicate invoice
- 1: Incomplete Outlook MSG file: Blue_Ocean_Invoice_Mail_01.msg. It contains no email or attachment content. In Outlook, open the original email and use File > Save As > Outlook Message Format (.msg), then upload that saved file.
- 1: Incomplete Outlook MSG file: Blue_Ocean_Invoice_Mail_02.msg. It contains no email or attachment content. In Outlook, open the original email and use File > Save As > Outlook Message Format (.msg), then upload that saved file.

## Complete results

See Invoice_Results.csv and Invoice_Test_Results.xlsx for every entry; Field_Comparisons.csv contains expected and extracted values for every scored field.
