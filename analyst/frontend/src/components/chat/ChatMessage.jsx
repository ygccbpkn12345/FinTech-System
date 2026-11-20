import { Button, Tag } from 'antd'
import StockResultCard from './StockResultCard'
import ToolStatusMessage from './ToolStatusMessage'

const MISSING_LABELS = {
  stockCode: '股票代码',
  analysisDate: '分析日期',
}

function MessageActions({ message, onAction }) {
  const actions = Array.isArray(message?.result?.actions) ? message.result.actions : []

  if (message.type === 'confirmation') {
    return (
      <div className="chat-message-actions">
        <Button size="small" type="primary" onClick={() => onAction?.(message, { type: 'confirm' })}>
          确认执行
        </Button>
        <Button size="small" onClick={() => onAction?.(message, { type: 'cancel' })}>
          取消
        </Button>
      </div>
    )
  }

  if (message.type !== 'error') return null

  const retry = actions.find((action) => action.type === 'retry')
  if (!retry && !message.retryable) return null

  return (
    <div className="chat-message-actions">
      <Button size="small" onClick={() => onAction?.(message, { type: 'retry' })}>
        {retry?.label || '重试'}
      </Button>
    </div>
  )
}

function ChatMessage({ message, onAction }) {
  if (!message) return null

  if (message.type === 'tool_progress') {
    return <ToolStatusMessage message={message} />
  }

  if (message.type === 'result' && message.result) {
    return <StockResultCard result={message.result} onAction={onAction} />
  }

  const isUser = message.role === 'user'
  const missing = Array.isArray(message.missingParameters) ? message.missingParameters : []

  return (
    <div className={`chat-message${isUser ? ' chat-message--user' : ' chat-message--assistant'}`}>
      {!isUser && <div className="chat-avatar">AI</div>}
      <div className={`chat-bubble${message.type === 'error' ? ' chat-bubble--error' : ''}`}>
        <div className="chat-text">{message.content}</div>
        {missing.length > 0 && (
          <div className="chat-param-hints">
            {missing.map((name) => (
              <Tag key={name}>{MISSING_LABELS[name] || name}</Tag>
            ))}
          </div>
        )}
        <MessageActions message={message} onAction={onAction} />
      </div>
    </div>
  )
}

export default ChatMessage
