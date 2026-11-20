import { Alert, Col, Collapse, Descriptions, Empty, Row, Tag } from 'antd'
import {
  BulbOutlined,
  DatabaseOutlined,
  EditOutlined,
  EyeOutlined,
  LineChartOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import TerminalCard from './TerminalCard'
import { formatWeight } from '@/utils/signalUtils'
import { normalizeReflectionPayload } from '@/utils/reflectionUtils'
import { DisplayParagraphs, DisplayStructuredBody } from '@/components/DisplayText'
import { cleanDisplayText } from '@/utils/displayTextUtils'

function ReflectionPanel({ reflection = {}, bare = false }) {
  const safe = normalizeReflectionPayload(reflection)

  const sections = [
    {
      key: 'weight',
      label: (
        <span className="reflection-section-label">
          <EditOutlined />
          分析师权重调整建议
        </span>
      ),
      children: (
        <div className="reflection-list">
          {safe.weightAdjustments.length ? (
            safe.weightAdjustments.map((item, index) => (
              <div key={item?.analystId ?? `weight-${index}`} className="reflection-item">
                <div className="reflection-item-header">
                  <Tag className="tag-neutral">{item?.analystId ?? '--'}</Tag>
                  <span className="reflection-weight-change">
                    {formatWeight(item?.currentWeight)} → {formatWeight(item?.suggestedWeight)}
                  </span>
                </div>
                <p>{cleanDisplayText(item?.reason) || '--'}</p>
              </div>
            ))
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无权重调整建议" />
          )}
        </div>
      ),
    },
    {
      key: 'blindspots',
      label: (
        <span className="reflection-section-label">
          <EyeOutlined />
          经理认知盲区
        </span>
      ),
      children: (
        <Row gutter={[12, 12]}>
          {safe.managerBlindSpots.length ? (
            safe.managerBlindSpots.map((item, index) => (
              <Col xs={24} md={8} key={item?.area ?? `blind-${index}`}>
                <div className="reflection-card">
                  <div className="reflection-card-title">{item?.area ?? '--'}</div>
                <DisplayParagraphs className="reflection-desc" children={item.description ?? '--'} />
                <div className="reflection-suggestion">
                  <BulbOutlined /> {cleanDisplayText(item?.suggestion) || '--'}
                </div>
                </div>
              </Col>
            ))
          ) : (
            <Col span={24}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无经理盲区记录" />
            </Col>
          )}
        </Row>
      ),
    },
    {
      key: 'risk',
      label: (
        <span className="reflection-section-label">
          <SafetyCertificateOutlined />
          风险管理者改进建议
        </span>
      ),
      children: (
        <Descriptions
          column={1}
          size="small"
          bordered
          className="reflection-descriptions"
          items={
            safe.riskControlImprovements.length
              ? safe.riskControlImprovements.map((item, i) => ({
                  key: i,
                  label: cleanDisplayText(item.item) || `建议 ${i + 1}`,
                  children: <DisplayStructuredBody item={item} />,
                }))
              : [{ key: 'empty', label: '—', children: '暂无风险管理者改进建议' }]
          }
        />
      ),
    },
    {
      key: 'prompt',
      label: (
        <span className="reflection-section-label">
          <EditOutlined />
          最终决策者提示词优化建议
        </span>
      ),
      children: (
        <div className="reflection-list">
          {safe.promptOptimizations.length ? (
            safe.promptOptimizations.map((item, i) => (
              <div key={i} className="reflection-item">
                <div className="reflection-item-header">
                  <strong>{cleanDisplayText(item.target) || `Prompt ${i + 1}`}</strong>
                </div>
                <DisplayStructuredBody item={item} />
              </div>
            ))
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 Prompt 优化建议" />
          )}
        </div>
      ),
    },
  ]

  const content = (
    <>
      <Alert
        type="info"
        showIcon
        icon={<LineChartOutlined />}
        message="文本梯度下降 · Text Gradient Descent"
        description={
          '反思者 Agent 不更新模型参数，而是通过分析本次决策偏差，' +
          '迭代优化各 Agent 的 Prompt 模板与路由策略——类比于在文本空间中进行"梯度下降"，' +
          '使后续决策质量逐步提升。'
        }
        className="reflection-gd-alert"
        style={{ marginBottom: 12 }}
      />

      <div className="reflection-meta">
        <BulbOutlined style={{ color: 'var(--accent-cyan)' }} />
        <DisplayParagraphs
          className="reflection-meta-text"
          children={safe.summary || safe.metaReflection || '暂无反思摘要'}
        />
      </div>

      <div className="reflection-memory">
        <DatabaseOutlined style={{ color: 'var(--accent-blue)' }} />
        <div>
          <div className="reflection-memory-title">反思记忆入库</div>
          <div className="reflection-memory-desc">
            系统将保存决策依据摘要、错误模式和反思记忆，用于 RAG 检索增强后续相似场景的分析质量。
          </div>
        </div>
      </div>

      <Collapse
        items={sections}
        bordered={false}
        className="reflection-collapse"
        defaultActiveKey={['weight', 'prompt']}
      />
    </>
  )

  if (bare) return content

  return (
    <TerminalCard
      title="反思层：反思记忆更新"
      subtitle="Reflection Layer"
      extra="Reflection Agent"
    >
      {content}
    </TerminalCard>
  )
}

export default ReflectionPanel
