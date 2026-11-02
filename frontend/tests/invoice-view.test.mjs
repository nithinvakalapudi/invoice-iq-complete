import assert from 'node:assert/strict'
import test from 'node:test'
import { display, displayAmount, filterResults, overviewColumns, statusLabel, statusTone } from '../src/invoice-view.js'

const records = [
  { mdm_row: { 'Vendor -As per MDM': 'Blue Ocean', 'Review status': 'SUCCESS', 'Billing Account': '000123' }, review_required: false },
  { mdm_row: { 'Vendor -As per MDM': 'Second Vendor', 'Review status': 'REVIEW_REQUIRED', 'Review reasons': 'Missing currency' }, review_required: true },
  { mdm_row: { 'Vendor -As per MDM': 'Third Vendor', 'Review status': 'FAILED' }, review_required: true },
  { mdm_row: { 'Vendor -As per MDM': 'Fourth Vendor', 'Review status': 'VALID' }, review_required: false },
]

test('null fields are blank but zero amounts and account leading zeros are preserved', () => {
  for (const value of [null, undefined, '']) assert.equal(display(value), '—')
  assert.equal(display(0), '0')
  assert.equal(display('000123'), '000123')
})
test('success labels do not conceal review or failed statuses', () => {
  assert.equal(statusLabel('SUCCESS'), 'Success')
  assert.equal(statusLabel('VALID'), 'Success')
  assert.equal(statusLabel('REVIEW_REQUIRED'), 'Review required')
  assert.equal(statusLabel('FAILED'), 'FAILED')
})
test('status colors distinguish success, warning, failure and skipped records', () => {
  assert.equal(statusTone('SUCCESS'), 'success')
  assert.equal(statusTone('REVIEW_REQUIRED'), 'warning')
  assert.equal(statusTone('FAILED'), 'danger')
  assert.equal(statusTone('SKIPPED'), 'neutral')
})
test('search is case-insensitive and trims surrounding whitespace', () => {
  assert.deepEqual(filterResults(records, '  BLUE ocean  ').map((entry) => entry.index), [0])
  assert.equal(filterResults(records, 'not-present').length, 0)
})
test('review filters reflect the actual review flag or status', () => {
  assert.deepEqual(filterResults(records, '', 'review').map((entry) => entry.index), [1, 2])
  assert.deepEqual(filterResults([{ mdm_row: { 'Review status': 'REVIEW_REQUIRED' } }], '', 'review').map((entry) => entry.index), [0])
})
test('successful filter recognizes both VALID and SUCCESS', () => {
  assert.deepEqual(filterResults(records, '', 'success').map((entry) => entry.index), [0, 3])
})
test('filtered review actions retain the original batch indices', () => {
  const shown = filterResults(records, 'Fourth')
  assert.equal(shown[0].index, 3)
  assert.equal(shown[0].result, records[3])
})
test('presentation never changes original invoice records', () => {
  const before = JSON.stringify(records)
  filterResults(records, 'Vendor', 'success')
  assert.equal(JSON.stringify(records), before)
  assert.equal(filterResults(records).length, records.length)
})
test('amounts are readable without losing precision or overwriting unknown values', () => {
  assert.equal(displayAmount('4500.00'), '4,500.00')
  assert.equal(displayAmount(0), '0.00')
  assert.equal(displayAmount('-1234.567'), '-1,234.567')
  assert.equal(displayAmount(null), '—')
  assert.equal(displayAmount('not extracted'), 'not extracted')
  assert.equal(displayAmount('1234567890123456789.00'), '1234567890123456789.00')
})
test('the compact view retains the essential accounting columns', () => {
  assert.equal(overviewColumns.length, 12)
  for (const name of ['Invoice Number', 'Billing Account', 'Currency', 'Net Amount', 'Tax Amount', 'Duplicate status', 'Review status']) assert.ok(overviewColumns.includes(name))
})

test('rejected invoices are separate from successful and review-needed records', () => {
  const rejected = { mdm_row: { 'Review status': 'REJECTED', 'Review reasons': 'Missing Service Date' }, validation_status: 'REJECTED', review_required: true }
  const batch = [...records, rejected]
  assert.deepEqual(filterResults(batch, '', 'rejected').map((entry) => entry.index), [4])
  assert.deepEqual(filterResults(batch, '', 'review').map((entry) => entry.index), [1, 2])
  assert.deepEqual(filterResults(batch, '', 'success').map((entry) => entry.index), [0, 3])
  assert.equal(statusLabel('REJECTED'), 'Rejected')
  assert.equal(statusTone('REJECTED'), 'danger')
  assert.equal(filterResults(batch, 'service date', 'rejected')[0].result, rejected)
  assert.equal(filterResults([{ validation_status: 'REJECTED', mdm_row: { 'Review status': 'SUCCESS' } }], '', 'success').length, 0)
})

test('overview includes region and invoice service dates', () => {
  assert.ok(overviewColumns.includes('Region'))
  assert.ok(overviewColumns.includes('Billing Start Date'))
  assert.ok(overviewColumns.includes('Billing End Date'))
})
