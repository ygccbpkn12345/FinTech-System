import { useEffect, useState } from 'react'
import { Badge, Divider, Layout, Menu, Space, Tag, Tooltip, Typography } from 'antd'
import {
  BarChartOutlined,
  BulbOutlined,
  ClockCircleOutlined,
  CloudServerOutlined,
  MessageOutlined,
  SettingOutlined,
  ApiOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { API_BASE_URL, USE_MOCK } from '@/api/analysisApi'
import dayjs from 'dayjs'

const { Header, Sider, Content } = Layout
const { Text } = Typography

const menuItems = [
  { key: '/chat', icon: <MessageOutlined />, label: '智能对话' },
  { key: '/dashboard', icon: <ThunderboltOutlined />, label: '智能分析' },
  { key: '/history', icon: <ClockCircleOutlined />, label: '历史记录' },
  { key: '/reflection', icon: <BulbOutlined />, label: '反思记忆' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统配置' },
  { key: '/algorithms', icon: <ApiOutlined />, label: '算法管理' },
]

function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [now, setNow] = useState(() => dayjs())

  useEffect(() => {
    const timer = setInterval(() => setNow(dayjs()), 1000)
    return () => clearInterval(timer)
  }, [])

  const selectedKey =
    menuItems.find((item) => location.pathname.startsWith(item.key))?.key ?? '/dashboard'

  return (
    <Layout className="app-layout">
      <Sider width={228} collapsedWidth={64} breakpoint="lg" className="app-sider">
        <div className="app-sider-logo">
          <div className="logo-icon">
            <BarChartOutlined />
          </div>
          <div>
            <div className="logo-text">Stock LLM Terminal</div>
            <div className="logo-sub">MULTI-AGENT DECISION</div>
          </div>
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          className="app-sider-menu"
        />
        <div className="app-sider-footer">
          <Tag className={USE_MOCK ? 'tag-neutral' : 'tag-cyan'}>
            {USE_MOCK ? 'Mock 模式' : '后端模式'}
          </Tag>
        </div>
      </Sider>

      <Layout>
        <Header className="app-layout-header">
          <div className="app-header-title">
            <span className="title-cn">多分析师股票智能决策系统</span>
            <span className="title-divider" />
            <span className="title-en">Multi-Agent Stock Decision System</span>
          </div>
          <Space size="middle" className="app-header-right" split={<Divider type="vertical" />}>
            <Tooltip title={API_BASE_URL}>
              <Space size={6} className="app-header-status">
                <Badge status="processing" color="#ff5a5a" />
                <CloudServerOutlined style={{ color: 'rgba(255,255,255,0.9)' }} />
                <Text style={{ color: 'rgba(255,255,255,0.88)', fontSize: 12 }}>
                  后端已连接
                </Text>
              </Space>
            </Tooltip>
            <Space size={6}>
              <ClockCircleOutlined style={{ color: 'rgba(255,255,255,0.7)' }} />
              <Text className="app-header-clock">{now.format('YYYY-MM-DD HH:mm:ss')}</Text>
            </Space>
            <Tag className="tag-neutral app-version-tag">v0.1.0</Tag>
          </Space>
        </Header>

        <Content className="app-main-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}

export default AppLayout
