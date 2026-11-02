# InvoiceIQ — demo video and presenter script

## Recommended format

**Title:** InvoiceIQ — Intelligent Invoice Workflow Orchestration
**Subtitle:** From invoice inbox to validated reports
**Length:** approximately 4–5 minutes
**Format:** real screen recording with your own narration; webcam optional
**Target output:** 1920 × 1080, 16:9, 30 fps, MP4 where your approved tool supports it

Show the application working, not an AI-generated imitation of its screens. A short
title card, one architecture image, and the actual workflow are sufficient.

## Which recording tool to use

| Tool | Best use | Important consideration |
| --- | --- | --- |
| Windows 11 Snipping Tool | Quick screen recording using an existing Windows tool | Use the Record option or Win + Shift + R. Check microphone availability in your installed version and make a short audio test. |
| OBS Studio | More control over local screen capture and narration | Use only if installed or approved by company IT. Select Window Capture and configure microphone audio. |
| Microsoft Clipchamp | Trimming clips, adding titles/captions, and exporting MP4 | Use an approved work account. Availability depends on your organization's enablement and license; work media/projects are stored in OneDrive/SharePoint. |

**Recommendation:** use OBS for a polished local recording if approved. Otherwise,
start with the existing Snipping Tool. Use Clipchamp for editing only when your
organization permits it. Do not move company footage into a personal editing account.

Official instructions:

- [Microsoft: Snipping Tool video capture](https://support.microsoft.com/en-gb/windows/apps/use-snipping-tool-to-capture-screenshots)
- [OBS: Quick Start Guide](https://obsproject.com/kb/quick-start-guide)
- [Microsoft: Clipchamp recording and editing](https://support.microsoft.com/en-us/clipchamp/how-to-make-a-screen-recording)
- [Microsoft: work-account availability](https://support.microsoft.com/en-us/clipchamp/how-to-access-microsoft-clipchamp-with-your-work-or-school-account)

## Prepare before recording

1. Open the app at <http://127.0.0.1:8505/> in a maximized browser window.
2. Use synthetic invoices, sample MDM/contract records, and a test Outlook folder.
   Hide real mailbox addresses, customer details, credentials, and unrelated notifications.
3. Prepare a successful invoice and one genuine exception, such as an unmatched vendor
   or a missing contract date. Label these as demonstration data.
4. Choose a new, unprocessed sample for the intake demonstration. Re-uploading the same
   invoice into existing history can correctly trigger duplicate review. If repeating a
   rehearsal, use isolated demo storage or open the saved batch instead of re-uploading it.
   Do not reset operational data merely to clean the recording.
5. Ensure Vendor Accounts and Contracts are ready before starting. A reliable account
   match and a uniquely matched contract with usable dates are prerequisites for the
   contract-verified export.
6. Keep classic Outlook open if demonstrating Run Outlook. Stage only approved test
   emails; successfully saved messages are marked read. Previously processed messages
   are skipped, so a second run may correctly report no new emails.
7. Open the architecture PNG in another window:
   `docs/architecture/top-level-architecture.png`.
8. Make a ten-second recording and play it back to check text readability and microphone audio.

The current project already contains synthetic PDF examples under
`local_data/generated_demo_2026-10-09/invoices/` and a sample manifest beside that folder.
Several examples are already in saved history. They are not evidence of general production accuracy.

## Recording steps

### OBS — if approved

1. Run the Auto-Configuration Wizard and choose recording as your intended use.
2. Add a Window Capture source for the application browser. Add the diagram/Outlook
   windows as separate sources if needed; avoid capturing unrelated desktop content.
3. Set a 1080p output and 30 fps if your computer supports that smoothly.
4. Select your microphone in Settings → Audio and verify that the mixer responds.
   Mute desktop audio unless the demonstration needs it.
5. Record each scene separately, or record one rehearsal followed by a final take.
6. Stop recording and review the entire file. If recording to MKV, remux to MP4 using
   OBS's remux facility when a supported MP4 deliverable is required.

### Snipping Tool — simplest alternative

1. Open Snipping Tool, choose Record → New, or press Win + Shift + R.
2. Select the browser region; check available microphone controls before starting.
3. Record the workflow, stop, and save the video.
4. If permitted, edit it in your approved Clipchamp environment. Otherwise keep the
   recording local and use an approved editor for narration or trimming.

### Editing

- Trim loading pauses and mistakes. Keep a truthful indication that processing took place;
  label accelerated footage or cuts rather than suggesting instant processing.
- Add the title and subtitle for approximately three seconds.
- Add brief labels: Invoice Intake → Local Extraction → MDM Match → Contract Check → Reports.
- Include captions if approved, and check every vendor name, account code, and technical term.
- Use your natural voice. Background music is optional and should not compete with narration.
- Export a 1080p MP4 if available. Play the final export and verify its sound before sharing.
- Share through the approved internal submission channel. A localhost link works only
  on the running computer and is not a remotely accessible demo link.

## Scene-by-scene script

Timings are approximate. Speak naturally and pause for each visible action.

### 1. Introduction — 0:00–0:25

**Show:** the home screen and the title “InvoiceIQ — Intelligent Invoice Workflow Orchestration.”

**Say:**

> Hello everyone. This is InvoiceIQ, our intelligent invoice workflow orchestration
> application. It connects invoice intake, data extraction, master-data matching,
> contract verification, and reporting in one workspace. The objective is to reduce
> repetitive manual work while keeping exceptions visible and decisions traceable.

### 2. Business problem — 0:25–0:55

**Show:** a simple “Before” list: Download → Type fields → Search MDM → Check contracts → Update spreadsheets.

**Say:**

> Previously, an operator had to find an invoice email, download its attachment,
> enter the details into a spreadsheet, identify the correct billing account, and
> check the contract manually. These disconnected steps created repeated work and
> opportunities for errors. We bring those steps into one consistent, connected workflow.

### 3. Architecture — 0:55–1:20

**Show:** the existing top-level architecture PNG; point from intake to reports.

**Say:**

> The React interface connects to a local Python processing service. PDF text or
> OCR feeds the local field extractor. Validation then checks the invoice, resolves
> its billing account against Vendor Accounts, and checks the linked contract.
> Saved history supplies cumulative CSV and Excel reports. Extraction runs locally.

### 4. Intake and extraction — 1:20–2:00

**Show:** briefly display the test invoice; select fresh demo files and click Process.
Show resulting vendor, invoice number, date, currency, service dates, net amount, and tax.
If available, briefly show classic Outlook's test Invoices folder and Run Outlook.

**Say:**

> Invoices can enter through manual uploads or the Invoices folder in classic Outlook.
> Supported uploads include PDFs, images, email files, ZIP archives, and spreadsheets.
> For email intake, only actual supported attachments enter the invoice pipeline.
> Here, I process a demonstration invoice. The application extracts its accounting
> fields and service details, then presents the results for validation and matching.

**If Outlook is unavailable:** do not imply a successful live mailbox connection.
Say: “This recording demonstrates manual intake; classic Outlook intake requires
the desktop application and an accessible test mailbox on the running computer.”

### 5. Vendor and Billing Account matching — 2:00–2:40

**Show:** the sample Vendor Accounts records, then Run MDM and the invoice's Billing Account.
Use All fields to show Region, Billing Account match status, and the matching reason.

**Say:**

> Vendor names may differ in punctuation, spacing, or legal suffixes. The matcher
> normalizes those differences and gives reliable exact matches priority. If a vendor
> has multiple billing accounts, the extracted region is compared with Restricted To
> to select the correct record. The Account value from that record becomes Billing
> Account in the invoice result. Ambiguous matches remain unresolved rather than guessed.

### 6. Contract verification — 2:40–3:10

**Show:** the matched Contract ID, Start Date and End Date, followed by the contract status.
If a prepared invalid case is available, show its actual reason and comment.

**Say:**

> Next, Billing Account is matched to Contract ID in the Contracts reference data.
> The current check requires a unique record with usable start and end dates.
> Missing or unusable dates produce a review reason and an invalid-contract comment
> where applicable. The application does not currently check whether invoice service
> dates fall within the contract range.

### 7. Validation and exception handling — 3:10–3:40

**Show:** Successful and Needs review filters; a genuine exception's Review reasons;
open Review details. Save a correction only if it was checked against the demo source.

**Say:**

> A complete invoice that passes the configured checks can be marked Success.
> Missing required fields, inconsistent amounts, possible duplicates, or unresolved
> reference checks are routed for review with a specific reason. The operator can
> inspect and correct the invoice against its source. Reviewed corrections can also
> support local model retraining. Completeness is field coverage, not verified accuracy.

### 8. Cumulative reports — 3:40–4:10

**Show:** expand Saved history, download the two cumulative CSV feeds, and open
Invoice_History.xlsx with the Invoice Data and Contract Verified sheets.

**Say:**

> Results are saved locally and accumulated across batches. The invoice-data report
> contains the requested business columns for all saved results. A second feed contains
> eligible successful invoices with matched contract dates and an Insert marker.
> CSV and Excel downloads support the next operational step without repeated manual
> consolidation. MDM reference masters themselves are not automatically changed.

### 9. Closing — 4:10–4:30

**Show:** return to the home screen or architecture; display “Connected workflow. Clear exceptions. Local processing.”

**Say:**

> InvoiceIQ turns a series of manual handoffs into a connected, auditable workflow.
> Its value is fewer repetitive steps, consistent checks, and clearer exception handling.
> The next step is a measured pilot on representative company invoices to establish
> accuracy, handling-time savings, and operational throughput. Thank you.

## How to present confidently

- Explain the problem before mentioning technologies.
- Say what the viewer should notice before clicking, then pause for the result.
- Keep narration focused on the output: extracted fields, correct account, contract result,
  and cumulative reports. Do not read every column aloud.
- Include one genuine exception. Explainable review is a control, not a failed demo.
- Prefer one small successful batch to a rushed 1,000-invoice demonstration.
- Do not execute Reset on operational data. If showing it, cancel the final confirmation.
- Keep technical detail brief unless the audience asks for it.

## Honest answers for common questions

**What model is used?** Local OCR/text parsing plus a scikit-learn logistic-regression
field selector and invoice parsers; not a new foundational LLM and not Gemini/Ollama.

**Does it update MDM?** It reads Vendor Accounts and Contracts and enriches invoice
output. It does not automatically write back to the reference masters.

**Does contract verification prove service-period coverage?** No. The current rule
checks the presence/usability of dates on a unique matched contract, not coverage.

**Is it 95% accurate on all invoices?** Do not claim that. Existing synthetic evaluation
results do not establish accuracy on unfamiliar real-company invoices. Measure a
separate, representative holdout set before making a production accuracy claim.

**What testing was performed?** The latest UI-change regression run passed 181 Python
tests and 10 frontend presentation-logic tests. These tests support implementation
behavior, not a claim of 100% extraction accuracy.

**Can it run every 30 minutes?** An optional per-user Windows scheduled task supports
recurring intake when installed and configured. It requires the user session and classic
Outlook; do not imply that an unattended mailbox/cloud service is already deployed.

**Are the demo emails real vendor contacts?** No. Synthetic examples use demonstration
addresses. Production Source email should come from an address printed on the invoice.

## Submission checklist

- [ ] Only authorized or synthetic data is visible.
- [ ] All shown fields and account matches agree with the demonstration sources.
- [ ] No API keys, environment secrets, or unrelated notifications appear.
- [ ] Narration is understandable and captions have been checked.
- [ ] Long waits are trimmed without misleading viewers about processing time.
- [ ] The two cumulative outputs are clearly distinguished.
- [ ] No unsupported accuracy, throughput, cost-saving, or compliance claim is made.
- [ ] The exported file plays correctly and its approved sharing permissions are tested.

**Suggested filename:** `InvoiceIQ_Demo.mp4`
