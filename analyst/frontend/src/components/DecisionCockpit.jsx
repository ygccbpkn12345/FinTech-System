import { Badge, Col, Divider, Row, Space, Statistic, Tag, Tooltip, Typography } from 'antd'
import { SafetyCertificateOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { getActionTheme, getRiskLevelTag } from '@/utils/signalUtils'
import EntryValidation from './EntryValidation'
import FinalDecisionCard from './FinalDecisionCard'

function computeRiskScore(riskAssessment = []) {
  if (!riskAssessment.length) return { score: 0, label: '—', level: 'low' }
  const map = { high: 82, medium: 55, low: 28 }
  const score = Math.round(
    riskAssessment.reduce((s, r) => s + (map[r.level] ?? 50), 0) / riskAssessment.length,
  )
  if (score >= 65) return { score, label: '偏高', level: 'medium' }
  if (score >= 40) return { score, label: '中等', level: 'medium' }
  return { score, label: '可控', level: 'low' }
}

function DecisionCockpit({ decision = {}, riskAssessment = [], taskId }) {
  const riskScore = computeRiskScore(riskAssessment)
  const riskTag = getRiskLevelTag(riskScore.level, riskScore.label)
  const theme = getActionTheme(decision?.action ?? '')
  const keyRisks = Array.isArray(decision?.keyRisks) ? decision.keyRisks : []
  const confidence =
    typeof decision?.confidence === 'number' ? Math.round(decision.confidence * 100) : 0

  return (
    <div className="decision-cockpit">
      <div className="cockpit-header">
        <div>
          <Space size={8}>
            <ThunderboltOutlined style={{ color: 'var(--accent-cyan)' }} />
            <div>
              <div className="cockpit-title">终局输出：决策驾驶舱</div>
              <div className="cockpit-subtitle">Final Decision Cockpit</div>
            </div>
          </Space>
        </div>
        <Badge status="success" text="Live" className="cockpit-live-badge" />
      </div>

      <div className="cockpit-scroll-body">
        <FinalDecisionCard decision={decision} compact riskScore={riskScore} />
        {taskId && ['买入', '谨慎买入'].includes(decision.action) && (
          <EntryValidation key={taskId} taskId={taskId} />
        )}

        <Row gutter={[8, 8]} className="cockpit-metric-row">
          <Col span={8}>
            <div className="cockpit-metric-card">
              <Statistic
                title="置信度"
                value={confidence}
                suffix="%"
                valueStyle={{ color: 'var(--accent-cyan)', fontSize: 18 }}
              />
            </div>
          </Col>
          <Col span={8}>
            <div className="cockpit-metric-card">
              <Statistic
                title="风险评分"
                value={riskScore.score}
                suffix="/100"
                valueStyle={{ fontSize: 18 }}
              />
            </div>
          </Col>
          <Col span={8}>
            <div className="cockpit-metric-card">
              <Statistic
                title="建议仓位"
                value={decision?.position ?? '--'}
                valueStyle={{ color: theme.accentColor, fontSize: 16 }}
              />
            </div>
          </Col>
        </Row>

        <Divider className="cockpit-divider" />

        <div className="cockpit-risk-strip">
          <SafetyCertificateOutlined style={{ color: 'var(--accent-cyan)' }} />
          <span className="cockpit-risk-label">综合风险</span>
          <Tag className={riskTag.className}>{riskTag.label}</Tag>
        </div>

        <div className="cockpit-mini-risks">
          {keyRisks.length ? (
            keyRisks.slice(0, 3).map((r) => (
              <Tooltip key={r} title={r}>
                <div className="cockpit-mini-risk-item">
                  <span className={`cockpit-dot cockpit-dot--${theme.type}`} />
                  <Typography.Text ellipsis className="cockpit-risk-text">
                    {r}
                  </Typography.Text>
                </div>
              </Tooltip>
            ))
          ) : (
            <Typography.Text type="secondary">暂无关键风险提示</Typography.Text>
          )}
        </div>
      </div>

      <div className="cockpit-footer">AI 决策建议 · 非真实交易指令</div>
    </div>
  )
}

export default DecisionCockpit
