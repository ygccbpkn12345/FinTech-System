import test from 'node:test'
import assert from 'node:assert/strict'
import { isMissingTaskError } from './chatTracking.js'

test('detects the backend message for an unknown task', () => {
  assert.equal(isMissingTaskError(new Error('任务不存在')), true)
  assert.equal(isMissingTaskError(new Error('Request failed with status code 404')), true)
})

test('network errors are not treated as missing tasks', () => {
  assert.equal(isMissingTaskError(new Error('Network Error')), false)
  assert.equal(isMissingTaskError(new Error('请求超时，请稍后重试')), false)
  assert.equal(isMissingTaskError(null), false)
  assert.equal(isMissingTaskError(undefined), false)
})
