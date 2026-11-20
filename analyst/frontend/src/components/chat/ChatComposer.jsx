import { Button, Input } from 'antd'
import { SendOutlined } from '@ant-design/icons'

const { TextArea } = Input

function ChatComposer({
  value = '',
  onChange,
  onSubmit,
  disabled = false,
  placeholder = '输入股票名称或代码，例如：预测中兴通讯',
}) {
  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSubmit?.()
    }
  }

  return (
    <div className="chat-composer">
      <div className="chat-composer-box">
        <TextArea
          value={value}
          onChange={(event) => onChange?.(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoSize={{ minRows: 1, maxRows: 6 }}
          variant="borderless"
          disabled={disabled}
        />
        <Button
          type="primary"
          shape="circle"
          icon={<SendOutlined />}
          onClick={onSubmit}
          disabled={disabled || !value.trim()}
          aria-label="发送"
        />
      </div>
      <div className="chat-composer-hint">Enter 发送，Shift + Enter 换行</div>
    </div>
  )
}

export default ChatComposer
