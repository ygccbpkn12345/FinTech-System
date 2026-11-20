import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_CONVERSATIONS,
  STORAGE_KEY,
  loadConversations,
  removeConversation,
  saveConversation,
} from './chatStorage.js'

function installStorage() {
  const map = new Map()
  const storage = {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    clear: () => map.clear(),
  }
  const original = globalThis.localStorage
  globalThis.localStorage = storage
  return {
    storage,
    restore() {
      if (original === undefined) delete globalThis.localStorage
      else globalThis.localStorage = original
    },
  }
}

function conversation(id, title, updatedAt, messages = []) {
  return { id, title, updatedAt, messages }
}

test('saved conversation is restored with title and messages', () => {
  const env = installStorage()
  try {
    saveConversation({
      id: 'c1',
      title: '预测中兴通讯',
      messages: [{ id: 'm1', role: 'user', type: 'text', content: '预测中兴通讯' }],
    })

    const [restored] = loadConversations()

    assert.equal(restored.id, 'c1')
    assert.equal(restored.title, '预测中兴通讯')
    assert.equal(restored.messages[0].content, '预测中兴通讯')
    assert.ok(restored.updatedAt > 0)
  } finally {
    env.restore()
  }
})

test('conversations load newest first', () => {
  const env = installStorage()
  try {
    env.storage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        conversation('old', '旧会话', 1000),
        conversation('new', '新会话', 3000),
        conversation('middle', '中间会话', 2000),
      ]),
    )

    assert.deepEqual(
      loadConversations().map((item) => item.id),
      ['new', 'middle', 'old'],
    )
  } finally {
    env.restore()
  }
})

test('saving keeps only the most recent conversations', () => {
  const env = installStorage()
  try {
    const seeded = []
    for (let index = 0; index < MAX_CONVERSATIONS + 5; index += 1) {
      seeded.push(conversation(`c${index}`, `会话${index}`, 1000 + index))
    }
    env.storage.setItem(STORAGE_KEY, JSON.stringify(seeded))

    const stored = saveConversation({ id: 'fresh', title: '最新', messages: [] })

    assert.equal(stored.length, MAX_CONVERSATIONS)
    assert.equal(stored[0].id, 'fresh')
    assert.equal(stored.some((item) => item.id === 'c0'), false)
  } finally {
    env.restore()
  }
})

test('saving an existing conversation updates it in place', () => {
  const env = installStorage()
  try {
    saveConversation({ id: 'c1', title: '旧标题', messages: [] })
    const stored = saveConversation({
      id: 'c1',
      title: '新标题',
      messages: [{ id: 'm1', role: 'user', type: 'text', content: '你好' }],
    })

    assert.equal(stored.length, 1)
    assert.equal(stored[0].title, '新标题')
    assert.equal(stored[0].messages.length, 1)
  } finally {
    env.restore()
  }
})

test('corrupt storage returns an empty list', () => {
  const env = installStorage()
  try {
    env.storage.setItem(STORAGE_KEY, '{not json')
    assert.deepEqual(loadConversations(), [])

    env.storage.setItem(STORAGE_KEY, JSON.stringify({ nope: true }))
    assert.deepEqual(loadConversations(), [])
  } finally {
    env.restore()
  }
})

test('messages keep the task id so a running task can be re-checked', () => {
  const env = installStorage()
  try {
    saveConversation({
      id: 'c1',
      title: '预测',
      messages: [
        { id: 'p1', role: 'tool', type: 'tool_progress', taskId: 'task-1', content: '运行中' },
      ],
    })

    const [restored] = loadConversations()
    assert.equal(restored.messages[0].taskId, 'task-1')
  } finally {
    env.restore()
  }
})

test('removeConversation drops only the requested entry', () => {
  const env = installStorage()
  try {
    saveConversation({ id: 'c1', title: '保留', messages: [] })
    saveConversation({ id: 'c2', title: '删除', messages: [] })

    const remaining = removeConversation('c2')

    assert.deepEqual(
      remaining.map((item) => item.id),
      ['c1'],
    )
    assert.deepEqual(
      loadConversations().map((item) => item.id),
      ['c1'],
    )
  } finally {
    env.restore()
  }
})
