// Presentation helpers never change an invoice or its exported data.
export const overviewColumns = [
  'Vendor -As per MDM', 'Invoice Number', 'Invoice Date', 'Region',
  'Billing Start Date', 'Billing End Date', 'Billing Account',
  'Currency', 'Net Amount', 'Tax Amount', 'Invoice Amount', 'Duplicate status', 'Review status',
]

export const display = (value) => value === null || value === undefined || value === '' ? '—' : String(value)
export const duplicateLabel = (value) => value === 'POSSIBLE_DUPLICATE' ? 'Duplicate' : value === 'NOT_DUPLICATE' ? 'Not duplicate' : display(value)
export const isRejected = (result) => result.mdm_row?.['Review status'] === 'REJECTED' || result.validation_status === 'REJECTED'
export const isSuccessful = (result) => !isRejected(result) && ['VALID', 'SUCCESS'].includes(result.mdm_row?.['Review status'])
export const needsReview = (result) => !isRejected(result) && (result.mdm_row?.['Review status'] === 'REVIEW_REQUIRED' || result.review_required === true)
export const statusTone = (status) => ['VALID', 'SUCCESS'].includes(status) ? 'success' : ['FAILED', 'REJECTED'].includes(status) ? 'danger' : status === 'SKIPPED' ? 'neutral' : 'warning'
export const statusLabel = (status) => ['VALID', 'SUCCESS'].includes(status) ? 'Success' : status === 'REJECTED' ? 'Rejected' : status === 'REVIEW_REQUIRED' ? 'Review required' : display(status)

export function filterResults(results, query = '', filter = 'all') {
  const search = query.trim().toLowerCase()
  return results.map((result, index) => ({ result, index })).filter(({ result }) =>
    (!search || JSON.stringify(result).toLowerCase().includes(search))
    && (filter === 'all' || (filter === 'review' ? needsReview(result) : filter === 'rejected' ? isRejected(result) : isSuccessful(result))))
}

export function displayAmount(value) {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text
  // Formatting is display-only, with no loss of source decimal precision.
  const decimals = text.split('.')[1]?.length || 0
  if (text.replace(/\D/g, '').length > 15 || decimals > 20) return text
  return Number(text).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: Math.max(2, decimals) })
}
