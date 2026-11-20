import test from 'node:test'
import assert from 'node:assert/strict'
import { appendAssistantMessages, createLocalMessage, resolveToolProgress } from './chatState.js'

test('assistant messages append without duplicating client message', () => {
  const current = [{ id: 'u1', role: 'user', type: 'text', content: '预测 000063' }]
  const next = appendAssistantMessages(current, [
    { id: 'a1', role: 'assistant', type: 'parameter_request', content: '请选择日期' },
  ])
  assert.equal(next.length, 2)
  assert.equal(next[1].id, 'a1')
})

test('assistant messages with existing ids are not duplicated', () => {
  const current = [{ id: 'a1', role: 'assistant', type: 'text', content: '你好' }]
  const next = appendAssistantMessages(current, [
    { id: 'a1', role: 'assistant', type: 'text', content: '你好' },
    { id: 'a2', role: 'assistant', type: 'text', content: '再问一次' },
  ])
  assert.deepEqual(
    next.map((message) => message.id),
    ['a1', 'a2'],
  )
})

test('completed result replaces matching progress message', () => {
  const next = resolveToolProgress(
    [{ id: 'p1', type: 'tool_progress', taskId: 'task-1' }],
    { id: 'r1', type: 'result', taskId: 'task-1' },
  )
  assert.equal(next[0].type, 'result')
  assert.equal(next[0].id, 'r1')
})

test('progress message keeps its position when resolved', () => {
  const next = resolveToolProgress(
    [
      { id: 'u1', type: 'text', content: '预测 000063' },
      { id: 'p1', type: 'tool_progress', taskId: 'task-1' },
    ],
    { id: 'r1', type: 'result', taskId: 'task-1' },
  )
  assert.deepEqual(
    next.map((message) => message.id),
    ['u1', 'r1'],
  )
})

test('result without matching progress is appended', () => {
  const next = resolveToolProgress(
    [{ id: 'u1', type: 'text', content: '你好' }],
    { id: 'r1', type: 'result', taskId: 'task-9' },
  )
  assert.deepEqual(
    next.map((message) => message.id),
    ['u1', 'r1'],
  )
})

test('state helpers never mutate the input list', () => {
  const current = [{ id: 'u1', type: 'text', content: '你好' }]
  appendAssistantMessages(current, [{ id: 'a1', type: 'text', content: '在' }])
  resolveToolProgress(current, { id: 'r1', type: 'result', taskId: 'task-1' })
  assert.deepEqual(current, [{ id: 'u1', type: 'text', content: '你好' }])
})

test('local messages get unique ids and the requested fields', () => {
  const first = createLocalMessage('user', 'text', '预测中兴通讯')
  const second = createLocalMessage('user', 'text', '预测中兴通讯')

  assert.equal(first.role, 'user')
  assert.equal(first.type, 'text')
  assert.equal(first.content, '预测中兴通讯')
  assert.ok(first.id)
  assert.notEqual(first.id, second.id)
})
