import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Drawer, Tag, Typography } from 'antd'
import { MenuOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import ChatComposer from '@/components/chat/ChatComposer'
import ChatMessage from '@/components/chat/ChatMessage'
import ChatSidebar from '@/components/chat/ChatSidebar'
import { API_BASE_URL, sendChatMessage } from '@/api/chatApi'
import {
  USE_MOCK,
  extractTaskErrorMessage,
  getAnalysisResult,
  getAnalysisStatus,
} from '@/api/analysisApi'
import { subscribeAnalysisEvents } from '@/api/analysisEvents'
import {
  appendAssistantMessages,
  createLocalMessage,
  resolveToolProgress,
} from '@/utils/chatState'
import { buildStockResultPayload } from '@/utils/chatResult'
import { isMissingTaskError } from '@/utils/chatTracking'
import {
  loadConversations,
  removeConversation,
  saveConversation,
} from '@/utils/chatStorage'

const { Title, Text } = Typography

const EXAMPLE_PROMPTS = [
  '预测中兴通讯',
  '介绍一下你能做什么',
  '更新 000063 的行情数据',
]

const POLL_INTERVAL_MS = 3000

function readInitialHistory() {
  const stored = loadConversations()
  const active = stored[0] || null
  return {
    conversations: stored,
    conversationId: active?.id ?? null,
    messages: active?.messages ?? [],
  }
}

function Chat() {
  const navigate = useNavigate()
  const initialRef = useRef(null)
  if (initialRef.current === null) initialRef.current = readInitialHistory()
  const initial = initialRef.current
  const [messages, setMessages] = useState(initial.messages)
  const [conversationId, setConversationId] = useState(initial.conversationId)
  const [conversations, setConversations] = useState(initial.conversations)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const trackedRef = useRef(new Map())
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  useEffect(() => {
    if (!conversationId || messages.length === 0) return
    const firstUser = messages.find(
      (message) => message.role === 'user' && message.type === 'text',
    )
    const title = firstUser?.content?.slice(0, 20) || '未命名会话'
    setConversations(saveConversation({ id: conversationId, title, messages }))
  }, [conversationId, messages])

  useEffect(
    () => () => {
      trackedRef.current.forEach((stop) => stop?.())
      trackedRef.current.clear()
    },
    [],
  )

  const startTracking = useCallback((taskId) => {
    if (trackedRef.current.has(taskId)) return

    let finished = false
    const cleanup = []
    const stop = () => cleanup.forEach((fn) => fn())

    const finalize = async () => {
      if (finished) return
      finished = true
      stop()
      trackedRef.current.delete(taskId)
      try {
        const analysis = await getAnalysisResult(taskId)
        const payload = buildStockResultPayload({ ...analysis, taskId })
        setMessages((current) =>
          resolveToolProgress(current, {
            id: `result-${taskId}`,
            role: 'tool',
            type: 'result',
            content: payload.summary,
            tool: 'stock_prediction',
            taskId,
            result: payload,
          }),
        )
      } catch (error) {
        setMessages((current) =>
          resolveToolProgress(current, {
            id: `error-${taskId}`,
            role: 'assistant',
            type: 'error',
            content: extractTaskErrorMessage(error, '分析任务失败，请重试。'),
            taskId,
            retryable: true,
          }),
        )
      }
    }

    if (!USE_MOCK && globalThis.EventSource) {
      cleanup.push(
        subscribeAnalysisEvents(
          taskId,
          {
            onCompleted: () => finalize(),
            onFailed: () => finalize(),
          },
          { baseUrl: API_BASE_URL },
        ),
      )
    }

    const timer = setInterval(async () => {
      try {
        const status = await getAnalysisStatus(taskId)
        if (status.status === 'completed' || status.status === 'failed') {
          await finalize()
          return
        }
        const progress = Number.isFinite(Number(status.progress)) ? Number(status.progress) : 0
        const node = status.currentNode || '分析进行中'
        setMessages((current) =>
          current.map((message) =>
            message.type === 'tool_progress' && message.taskId === taskId
              ? { ...message, content: `${node} · ${progress}%` }
              : message,
          ),
        )
      } catch (error) {
        if (!isMissingTaskError(error)) {
          // 网络抖动时继续轮询，避免误报任务失败
          return
        }
        finished = true
        stop()
        trackedRef.current.delete(taskId)
        setMessages((current) =>
          resolveToolProgress(current, {
            id: `error-${taskId}`,
            role: 'assistant',
            type: 'error',
            content: '该分析任务已不存在（服务可能已重启），请重新发起分析。',
            taskId,
          }),
        )
      }
    }, POLL_INTERVAL_MS)
    cleanup.push(() => clearInterval(timer))

    trackedRef.current.set(taskId, stop)
  }, [])

  useEffect(() => {
    messages.forEach((message) => {
      if (message.type === 'tool_progress' && message.taskId) {
        startTracking(message.taskId)
      }
    })
  }, [messages, startTracking])

  const submitMessage = useCallback(
    async (rawText) => {
      const content = String(rawText || '').trim()
      if (!content || sending) return

      const userMessage = createLocalMessage('user', 'text', content)
      setMessages((current) => appendAssistantMessages(current, [userMessage]))
      setInput('')
      setSending(true)

      try {
        const payload = await sendChatMessage({
          conversationId,
          message: content,
          clientMessageId: userMessage.id,
        })
        if (conversationId && conversationId !== payload.conversationId) {
          // 服务端会话已过期并重建：移除本地旧 ID，避免出现两条会话
          removeConversation(conversationId)
        }
        setConversationId(payload.conversationId)
        setMessages((current) =>
          appendAssistantMessages(current, payload.messages || []),
        )
      } catch (error) {
        setMessages((current) =>
          appendAssistantMessages(current, [
            createLocalMessage(
              'assistant',
              'error',
              error?.message || '发送失败，请重试',
              { retryable: true },
            ),
          ]),
        )
      } finally {
        setSending(false)
      }
    },
    [conversationId, sending],
  )

  const handleAction = useCallback(
    (message, action) => {
      if (!action) return
      if (action.type === 'navigate') {
        navigate(action.target || '/dashboard', {
          state: { taskId: action.value, fromChat: true },
        })
        return
      }
      if (action.type === 'retry') {
        const lastUser = [...messages]
          .reverse()
          .find((item) => item.role === 'user' && item.type === 'text')
        if (lastUser) submitMessage(lastUser.content)
        return
      }
      if (action.type === 'confirm') {
        submitMessage('确认')
        return
      }
      if (action.type === 'cancel') {
        submitMessage('取消')
      }
    },
    [messages, submitMessage],
  )

  const handleNewConversation = () => {
    trackedRef.current.forEach((stop) => stop?.())
    trackedRef.current.clear()
    setMessages([])
    setConversationId(null)
    setInput('')
    setSidebarOpen(false)
  }

  const handleSelectConversation = (item) => {
    const stored = loadConversations().find((entry) => entry.id === item?.id)
    if (stored) {
      trackedRef.current.forEach((stop) => stop?.())
      trackedRef.current.clear()
      setConversationId(stored.id)
      setMessages(stored.messages)
      setInput('')
    }
    setSidebarOpen(false)
  }

  const sidebarProps = {
    conversations,
    activeId: conversationId,
    onNew: handleNewConversation,
    onSelect: handleSelectConversation,
  }

  return (
    <div className="chat-shell">
      <div className="chat-shell-sidebar">
        <ChatSidebar {...sidebarProps} />
      </div>

      <main className="chat-main">
        <header className="chat-header">
          <Button
            type="text"
            icon={<MenuOutlined />}
            className="chat-menu-button"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开会话列表"
          />
          <div className="chat-header-title">AnalystVerse 智能对话</div>
          <Tag className="chat-header-tag">DeepSeek 路由</Tag>
        </header>

        <div className="chat-scroll">
          <div className="chat-thread">
            {messages.length === 0 ? (
              <div className="chat-welcome">
                <Title level={2} className="chat-welcome-title">
                  今天想分析哪只股票？
                </Title>
                <Text type="secondary" className="chat-welcome-sub">
                  可以直接聊天，也可以让我启动股票预测或更新行情数据。
                </Text>
                <div className="chat-examples">
                  {EXAMPLE_PROMPTS.map((example) => (
                    <button
                      key={example}
                      type="button"
                      className="chat-example"
                      onClick={() => submitMessage(example)}
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  onAction={handleAction}
                />
              ))
            )}
            {sending && (
              <div className="chat-typing" aria-label="正在回复">
                <span />
                <span />
                <span />
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="chat-composer-wrap">
          <ChatComposer
            value={input}
            onChange={setInput}
            onSubmit={() => submitMessage(input)}
            disabled={sending}
          />
        </div>
      </main>

      <Drawer
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        placement="left"
        width={272}
        styles={{ body: { padding: 0 } }}
        className="chat-drawer"
      >
        <ChatSidebar {...sidebarProps} />
      </Drawer>
    </div>
  )
}

export default Chat
