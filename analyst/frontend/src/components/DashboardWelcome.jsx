import { Card, Empty, Space, Typography } from 'antd'
import {
  ApartmentOutlined,
  LineChartOutlined,
  RobotOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'

const FEATURES = [
  { icon: <TeamOutlined />, title: '五位分析师', desc: '市场 · 新闻 · 行业 · 公司 · 动量' },
  { icon: <ApartmentOutlined />, title: '经理决策树', desc: '路由权重 · 风险评估 · 反思记忆' },
  { icon: <LineChartOutlined />, title: '行情驱动', desc: 'K 线趋势 · 标的基础数据' },
  { icon: <ThunderboltOutlined />, title: '决策驾驶舱', desc: '最终动作 · 仓位 · 置信度' },
]

function DashboardWelcome() {
  return (
    <div className="dashboard-welcome">
      <Empty
        image={<RobotOutlined className="dashboard-welcome-icon" />}
        description={
          <Space direction="vertical" size={4}>
            <Typography.Title level={4} className="dashboard-welcome-title">
              Multi-Agent 智能决策工作台
            </Typography.Title>
            <Typography.Text type="secondary">
              输入股票代码与分析日期，启动真实多智能体分析流程
            </Typography.Text>
          </Space>
        }
      />

      <div className="dashboard-feature-grid">
        {FEATURES.map((f) => (
          <Card key={f.title} size="small" className="dashboard-feature-card" bordered={false}>
            <Space align="start">
              <span className="dashboard-feature-icon">{f.icon}</span>
              <div>
                <Typography.Text strong>{f.title}</Typography.Text>
                <Typography.Paragraph type="secondary" className="dashboard-feature-desc">
                  {f.desc}
                </Typography.Paragraph>
              </div>
            </Space>
          </Card>
        ))}
      </div>
    </div>
  )
}

export default DashboardWelcome
