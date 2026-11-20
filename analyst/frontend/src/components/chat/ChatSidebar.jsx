import { Button, Menu, Typography } from 'antd'
import {
  BarChartOutlined,
  BulbOutlined,
  ClockCircleOutlined,
  MessageOutlined,
  PlusOutlined,
  SettingOutlined,
  ApiOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Text } = Typography

const NAV_ITEMS = [
  { key: '/dashboard', icon: <BarChartOutlined />, label: '完整分析' },
  { key: '/history', icon: <ClockCircleOutlined />, label: '历史记录' },
  { key: '/reflection', icon: <BulbOutlined />, label: '反思记忆' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统配置' },
  { key: '/algorithms', icon: <ApiOutlined />, label: '算法管理' },
]

function ChatSidebar({ conversations = [], activeId, onNew, onSelect }) {
  const navigate = useNavigate()

  return (
    <aside className="chat-sidebar">
      <div className="chat-sidebar-brand">
        <div className="chat-brand-icon">
          <MessageOutlined />
        </div>
        <div>
          <div className="chat-brand-title">AnalystVerse</div>
          <div className="chat-brand-sub">CHAT TOOL ROUTER</div>
        </div>
      </div>

      <Button
        block
        icon={<PlusOutlined />}
        className="chat-new-button"
        onClick={() => onNew?.()}
      >
        新对话
      </Button>

      <div className="chat-history">
        <div className="chat-history-title">最近会话</div>
        {conversations.length === 0 ? (
          <Text className="chat-history-empty">还没有会话，先问一个问题吧</Text>
        ) : (
          conversations.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`chat-history-item${item.id === activeId ? ' is-active' : ''}`}
              onClick={() => onSelect?.(item)}
            >
              {item.title || '未命名会话'}
            </button>
          ))
        )}
      </div>

      <Menu
        mode="inline"
        items={NAV_ITEMS}
        className="chat-sidebar-menu"
        onClick={({ key }) => navigate(key)}
      />
    </aside>
  )
}

export default ChatSidebar
