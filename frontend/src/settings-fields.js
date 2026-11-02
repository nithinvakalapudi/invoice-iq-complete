export const locationFields = [
  ['invoice_input_folder', 'Invoice input folder (optional)', 'Leave blank for manual uploads', 'Leave blank to upload files manually. Or enter a folder and use Run input folder.'],
  ['output_folder', 'Output folder', 'C:\\InvoiceData\\Output', 'Cumulative CSV and Excel reports are saved here. Existing history is retained.'],
  ['master_excel_filename', 'Master Excel filename', 'Invoice_History.xlsx', 'Enter a filename ending in .xlsx, not a folder path.'],
  ['mdm_folder', 'MDM folder — Vendor Accounts & Contracts', 'C:\\InvoiceData\\MDM', 'Add today’s InvoiceMDM and Contracts CSV/XLSX exports; each filename must contain its keyword and today’s YYYYMMDD. Billing Account is read from Account Number. Older dated exports are ignored.'],
]

export function settingsPayload(draft, threshold, tolerance) {
  return {
    ...Object.fromEntries(locationFields.map(([key]) => [key, (draft[key] || '').trim()])),
    revision: draft.revision || '', review_threshold: Number(threshold), rounding_tolerance: Number(tolerance),
  }
}

export function settingsError(value) {
  if (!value.output_folder) return 'Enter an output folder.'
  if (!/^[^<>:"/\\|?*\x00-\x1f]+\.xlsx$/i.test(value.master_excel_filename)) return 'Enter a simple .xlsx filename without a folder path.'
  if (!Number.isFinite(value.review_threshold) || value.review_threshold < 1 || value.review_threshold > 100) return 'Review threshold must be 1–100%.'
  if (!Number.isFinite(value.rounding_tolerance) || value.rounding_tolerance < 0 || value.rounding_tolerance > 100) return 'Rounding tolerance must be 0–100.'
  return ''
}
