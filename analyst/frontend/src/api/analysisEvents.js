function joinUrl(baseUrl, path) {
  return `${String(baseUrl ?? '').replace(/\/$/, '')}${path}`
}

function parseEvent(message, type) {
  const data = JSON.parse(message.data || '{}')
  return {
    id: Number(message.lastEventId || 0),
    type,
    ...data,
  }
}

export function subscribeAnalysisEvents(taskId, handlers = {}, options = {}) {
  const EventSourceClass = options.EventSourceClass ?? globalThis.EventSource
  if (!EventSourceClass) {
    throw new Error('当前环境不支持 EventSource')
  }

  const url = joinUrl(
    options.baseUrl,
    `/api/analyze/events/${encodeURIComponent(taskId)}`,
  )
  const source = new EventSourceClass(url)
  let lastId = 0
  let closed = false

  const consume = (type, handler, terminal = false) => (message) => {
    let event
    try {
      event = parseEvent(message, type)
    } catch (error) {
      handlers.onProtocolError?.(error)
      return
    }
    if (event.id <= lastId) return
    lastId = event.id
    handler?.(event)
    if (terminal) close()
  }

  const close = () => {
    if (closed) return
    closed = true
    source.close()
  }

  source.addEventListener('module_completed', consume('module_completed', handlers.onModule))
  source.addEventListener('completed', consume('completed', handlers.onCompleted, true))
  source.addEventListener('failed', consume('failed', handlers.onFailed, true))
  source.onopen = () => handlers.onOpen?.()
  source.onerror = (error) => {
    if (!closed) handlers.onConnectionError?.(error)
  }

  return close
}
