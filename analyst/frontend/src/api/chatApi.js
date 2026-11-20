/** 聊天接口客户端：统一消息协议的唯一出口。 */

import { API_BASE_URL } from './apiBaseUrl.js'

export { API_BASE_URL }

const CHAT_TIMEOUT_MS = 120000

async function readDetail(response) {
  try {
    const payload = await response.json()
    if (payload && typeof payload.detail === 'string') return payload.detail
    if (payload && typeof payload.message === 'string') return payload.message
  } catch {
    // 忽略非 JSON 响应
  }
  return ''
}

export async function sendChatMessage({ conversationId, message, clientMessageId }) {
  const body = { message, clientMessageId }
  if (conversationId) body.conversationId = conversationId

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS)

  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/chat/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('聊天请求超时，请稍后重试')
    }
    throw new Error('后端服务不可用，请检查 FastAPI 是否启动')
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    const detail = await readDetail(response)
    throw new Error(detail || `聊天请求失败（${response.status}）`)
  }

  return response.json()
}

export default sendChatMessage
