import assert from 'node:assert/strict'
import test from 'node:test'

import { subscribeAnalysisEvents } from './analysisEvents.js'


class FakeEventSource {
  static instances = []

  constructor(url) {
    this.url = url
    this.listeners = new Map()
    this.closed = false
    FakeEventSource.instances.push(this)
  }

  addEventListener(name, listener) {
    this.listeners.set(name, listener)
  }

  emit(name, data, lastEventId) {
    this.listeners.get(name)?.({ data: JSON.stringify(data), lastEventId: String(lastEventId) })
  }

  close() {
    this.closed = true
  }
}


test('normalizes module events and ignores duplicate ids', () => {
  const received = []
  const close = subscribeAnalysisEvents(
    'task 1',
    { onModule: (event) => received.push(event) },
    { EventSourceClass: FakeEventSource, baseUrl: 'http://api.test' },
  )
  const source = FakeEventSource.instances.at(-1)

  source.emit('module_completed', { module: 'market', result: { summary: 'ready' } }, 1)
  source.emit('module_completed', { module: 'market', result: { summary: 'duplicate' } }, 1)

  assert.equal(source.url, 'http://api.test/api/analyze/events/task%201')
  assert.deepEqual(received, [
    { id: 1, type: 'module_completed', module: 'market', result: { summary: 'ready' } },
  ])
  close()
  assert.equal(source.closed, true)
})


test('terminal events close the source and network errors remain reconnectable', () => {
  const states = []
  const failures = []
  subscribeAnalysisEvents(
    'task-2',
    {
      onConnectionError: () => states.push('reconnecting'),
      onFailed: (event) => failures.push(event.message),
    },
    { EventSourceClass: FakeEventSource, baseUrl: '' },
  )
  const source = FakeEventSource.instances.at(-1)

  source.onerror()
  assert.deepEqual(states, ['reconnecting'])
  assert.equal(source.closed, false)

  source.emit('failed', { status: 'failed', message: 'safe failure' }, 3)
  assert.deepEqual(failures, ['safe failure'])
  assert.equal(source.closed, true)
})


test('completed event invokes handler and closes explicitly', () => {
  let completed = 0
  subscribeAnalysisEvents(
    'task-3',
    { onCompleted: () => completed += 1 },
    { EventSourceClass: FakeEventSource },
  )
  const source = FakeEventSource.instances.at(-1)

  source.emit('completed', { status: 'completed' }, 2)

  assert.equal(completed, 1)
  assert.equal(source.closed, true)
})
