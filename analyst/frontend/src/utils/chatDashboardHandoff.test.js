import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveChatHandoff } from './chatDashboardHandoff.js'

test('chat handoff requests existing result without starting another task', () => {
  assert.deepEqual(resolveChatHandoff({ taskId: 'task-1', fromChat: true }), {
    taskId: 'task-1',
    shouldLoadResult: true,
    shouldStartAnalysis: false,
  })
})

test('plain dashboard visits are not handoffs', () => {
  assert.equal(resolveChatHandoff(undefined), null)
  assert.equal(resolveChatHandoff({}), null)
  assert.equal(resolveChatHandoff({ taskId: 'task-1' }), null)
  assert.equal(resolveChatHandoff({ fromChat: true }), null)
})
