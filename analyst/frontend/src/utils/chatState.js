/** 聊天消息的纯状态归并函数，始终保持不可变更新。 */

function nextId() {
  const cryptoApi = globalThis.crypto
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID()
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function createLocalMessage(role, type, content, extra = {}) {
  return {
    id: nextId(),
    role,
    type,
    content,
    ...extra,
  }
}

export function appendAssistantMessages(messages, incoming) {
  const list = Array.isArray(messages) ? messages : []
  const additions = Array.isArray(incoming) ? incoming : [incoming]
  const existingIds = new Set(list.map((message) => message?.id).filter(Boolean))
  const next = [...list]

  for (const message of additions) {
    if (!message) continue
    if (message.id && existingIds.has(message.id)) continue
    if (message.id) existingIds.add(message.id)
    next.push(message)
  }

  return next
}

export function resolveToolProgress(messages, incoming) {
  const list = Array.isArray(messages) ? messages : []
  if (!incoming) return [...list]

  const index = incoming.taskId
    ? list.findIndex(
        (message) =>
          message?.type === 'tool_progress' && message?.taskId === incoming.taskId,
      )
    : -1

  if (index === -1) return appendAssistantMessages(list, [incoming])

  const next = [...list]
  next[index] = { ...list[index], ...incoming }
  return next
}
