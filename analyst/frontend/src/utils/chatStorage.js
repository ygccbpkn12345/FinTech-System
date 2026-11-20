/** 浏览器本地会话历史：版本化存储、排序与条数上限。 */

export const STORAGE_KEY = 'analystverse_chat_history_v1'
export const MAX_CONVERSATIONS = 50

function storage() {
  try {
    return globalThis.localStorage || null
  } catch {
    return null
  }
}

function normalizeConversation(item) {
  if (!item || typeof item !== 'object' || !item.id) return null
  return {
    id: String(item.id),
    title: typeof item.title === 'string' && item.title ? item.title : '未命名会话',
    updatedAt: Number(item.updatedAt) || 0,
    messages: Array.isArray(item.messages) ? item.messages : [],
  }
}

export function loadConversations() {
  const store = storage()
  if (!store) return []

  try {
    const raw = store.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .map(normalizeConversation)
      .filter(Boolean)
      .sort((left, right) => right.updatedAt - left.updatedAt)
  } catch {
    return []
  }
}

export function saveConversation(conversation) {
  if (!conversation?.id) return loadConversations()

  const entry = normalizeConversation({
    ...conversation,
    updatedAt: Date.now(),
  })
  const conversations = loadConversations().filter((item) => item.id !== entry.id)
  conversations.push(entry)
  const trimmed = conversations
    .sort((left, right) => right.updatedAt - left.updatedAt)
    .slice(0, MAX_CONVERSATIONS)

  persist(trimmed)
  return trimmed
}

export function removeConversation(conversationId) {
  const conversations = loadConversations().filter(
    (item) => item.id !== conversationId,
  )
  persist(conversations)
  return conversations
}

function persist(conversations) {
  const store = storage()
  if (!store) return
  try {
    store.setItem(STORAGE_KEY, JSON.stringify(conversations))
  } catch {
    // 存储空间不足时保留内存中的会话列表
  }
}
