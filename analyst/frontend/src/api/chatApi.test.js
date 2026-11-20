import test from 'node:test'
import assert from 'node:assert/strict'
import { API_BASE_URL, sendChatMessage } from './chatApi.js'
import { normalizeApiBaseUrl } from './apiBaseUrl.js'

test('API addresses keep chat requests on the intended host', () => {
  const origin = 'http://127.0.0.1:5173'
  for (const base of ['', '/', '///']) {
    const url = new URL(`${normalizeApiBaseUrl(base)}/api/chat/messages`, origin)
    assert.equal(url.origin, origin)
    assert.equal(url.pathname, '/api/chat/messages')
  }
  for (const base of ['http://127.0.0.1:8000', 'http://127.0.0.1:8000/']) {
    const url = new URL(`${normalizeApiBaseUrl(base)}/api/chat/messages`, origin)
    assert.equal(url.origin, 'http://127.0.0.1:8000')
    assert.equal(url.pathname, '/api/chat/messages')
  }
  assert.equal(normalizeApiBaseUrl('https://example.com/backend/'), 'https://example.com/backend')
})

function stubFetch(handler) {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    return handler(url, init)
  }
  return {
    calls,
    restore() {
      globalThis.fetch = original
    },
  }
}

test('sendChatMessage posts message and client id', async () => {
  const stub = stubFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ conversationId: 'c1', messages: [] }),
  }))

  try {
    const payload = await sendChatMessage({
      conversationId: 'c1',
      message: '预测 000063',
      clientMessageId: 'client-1',
    })

    assert.equal(stub.calls[0].url, `${API_BASE_URL}/api/chat/messages`)
    assert.equal(stub.calls[0].init.method, 'POST')
    assert.deepEqual(JSON.parse(stub.calls[0].init.body), {
      conversationId: 'c1',
      message: '预测 000063',
      clientMessageId: 'client-1',
    })
    assert.equal(payload.conversationId, 'c1')
  } finally {
    stub.restore()
  }
})

test('sendChatMessage omits an empty conversation id', async () => {
  const stub = stubFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ conversationId: 'c2', messages: [] }),
  }))

  try {
    await sendChatMessage({ conversationId: null, message: '你好', clientMessageId: 'c2' })
    assert.deepEqual(JSON.parse(stub.calls[0].init.body), {
      message: '你好',
      clientMessageId: 'c2',
    })
  } finally {
    stub.restore()
  }
})

test('sendChatMessage surfaces backend detail on failure', async () => {
  const stub = stubFetch(async () => ({
    ok: false,
    status: 400,
    json: async () => ({ detail: '消息不能为空' }),
  }))

  try {
    await assert.rejects(
      () => sendChatMessage({ message: ' ', clientMessageId: 'c3' }),
      /消息不能为空/,
    )
  } finally {
    stub.restore()
  }
})
