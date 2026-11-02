import assert from 'node:assert/strict'
import test from 'node:test'
import { locationFields, settingsError, settingsPayload } from '../src/settings-fields.js'

test('location controls omit database and API credentials and include one shared MDM folder', () => {
  assert.deepEqual(locationFields.map(([key]) => key), ['invoice_input_folder', 'output_folder', 'master_excel_filename', 'mdm_folder'])
})
test('saved payload allows optional manual input and a 90% review threshold', () => {
  const payload = settingsPayload({ output_folder: ' C:\\Output ', master_excel_filename: ' master.xlsx ', mdm_folder: ' C:\\MDM ', revision: 'version' }, 90, .02)
  assert.equal(payload.invoice_input_folder, '')
  assert.equal(payload.output_folder, 'C:\\Output')
  assert.equal(payload.mdm_folder, 'C:\\MDM')
  assert.equal(payload.revision, 'version')
  assert.equal(settingsError(payload), '')
})
test('invalid filename, folder and validation ranges show actionable errors', () => {
  const valid = settingsPayload({ output_folder: 'C:\\Output', master_excel_filename: 'master.xlsx' }, 95, .02)
  for (const change of [{ output_folder: '' }, { master_excel_filename: '../master.xlsx' }, { review_threshold: 0 }, { review_threshold: NaN }, { review_threshold: 101 }, { rounding_tolerance: -1 }]) assert.ok(settingsError({ ...valid, ...change }))
})
