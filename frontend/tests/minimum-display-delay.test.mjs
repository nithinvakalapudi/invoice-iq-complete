import assert from 'node:assert/strict'
import test from 'node:test'
import { performance } from 'node:perf_hooks'
import { withMinimumDisplayDelay } from '../src/minimum-display-delay.js'

test('starts the request immediately and waits before revealing a fast result', async () => {
  let started = false
  const start = performance.now()
  const pending = withMinimumDisplayDelay(() => {
    started = true
    return Promise.resolve('matched')
  }, 30)
  assert.equal(started, true)
  assert.equal(await pending, 'matched')
  assert.ok(performance.now() - start >= 25)
})

test('does not add a second full pause after a slow request', async () => {
  const start = performance.now()
  const result = await withMinimumDisplayDelay(
    () => new Promise((resolve) => setTimeout(() => resolve('checked'), 50)), 20,
  )
  assert.equal(result, 'checked')
  assert.ok(performance.now() - start < 250)
})
