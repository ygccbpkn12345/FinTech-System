import { Alert, Empty, List, Table, Tag } from 'antd'
import { SafetyCertificateOutlined, WarningOutlined } from '@ant-design/icons'
import { DisplayParagraphs } from '@/components/DisplayText'
import { cleanDisplayText } from '@/utils/displayTextUtils'
import { getRiskLevelTag } from '@/utils/signalUtils'

function RiskPanel({ riskAssessment = [], compact = false, bare = false }) {
  const riskList = Array.isArray(riskAssessment)
    ? riskAssessment
    : Array.isArray(riskAssessment?.items)
      ? riskAssessment.items
      : Array.isArray(riskAssessment?.list)
        ? riskAssessment.list
        : []

  const levelCounts = riskList.reduce((acc, r) => {
    if (r?.level) acc[r.level] = (acc[r.level] || 0) + 1
    return acc
  }, {})

  const hasHigh = (levelCounts.high ?? 0) > 0
  const hasMedium = (levelCounts.medium ?? 0) > 0

  const columns = [
    {
      title: '风险类型',
      dataIndex: 'riskType',
      key: 'riskType',
      width: 120,
      render: (text, record) => (
        <span className={`risk-type-cell risk-type-cell--${record.level}`}>
          <WarningOutlined style={{ marginRight: 6 }} />
          {text}
        </span>
      ),
    },
    {
      title: '等级',
      dataIndex: 'level',
      key: 'level',
      width: 72,
      align: 'center',
      render: (level, record) => {
        const tag = getRiskLevelTag(level, record.levelLabel)
        return <Tag className={tag.className}>{tag.label}</Tag>
      },
    },
    {
      title: '风险解释',
      dataIndex: 'explanation',
      key: 'explanation',
      ellipsis: true,
      render: (text) => <span className="risk-explain-cell">{cleanDisplayText(text) || '--'}</span>,
    },
    {
      title: '缓解建议',
      dataIndex: 'mitigation',
      key: 'mitigation',
      ellipsis: true,
      render: (text) => <span className="risk-mitigate-cell">{cleanDisplayText(text) || '--'}</span>,
    },
  ]

  if (compact) {
    const topRisks = [...riskList].sort((a, b) => {
      const order = { high: 0, medium: 1, low: 2 }
      return (order[a.level] ?? 9) - (order[b.level] ?? 9)
    })

    return (
      <TerminalCard title="风控层：风险管理评估" extra="Risk Summary">
        <div className="risk-summary-bar">
          {['high', 'medium', 'low'].map((level) =>
            levelCounts[level] ? (
              <div key={level} className="risk-summary-item">
                <Tag className={getRiskLevelTag(level).className}>
                  {level === 'high' ? '高' : level === 'medium' ? '中' : '低'}
                </Tag>
                <span className="risk-summary-count">{levelCounts[level]}</span>
              </div>
            ) : null,
          )}
        </div>
        <List
          size="small"
          dataSource={topRisks.slice(0, 3)}
          renderItem={(item) => {
            const tag = getRiskLevelTag(item.level, item.levelLabel)
            return (
              <List.Item className="risk-compact-item">
                <Tag className={tag.className}>{tag.label}</Tag>
                <span>{item.riskType}</span>
              </List.Item>
            )
          }}
        />
      </TerminalCard>
    )
  }

  const content = (
    <>
      {riskList.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无风险评估条目，请检查后端 riskAssessment 或 finalDecision.keyRisks"
          style={{ margin: '24px 0' }}
        />
      ) : (
        <>
      <Alert
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
        message="针对经理决策分支的风控审查"
        description="风险管理者 Agent 对经理层各决策分支进行独立评估，识别潜在风险并给出缓解建议。"
        className="risk-panel-alert risk-panel-alert--info"
        style={{ marginBottom: 12 }}
      />

      {hasHigh && (
        <Alert
          type="error"
          showIcon
          message={`检测到 ${levelCounts.high} 项高风险，建议经理重新评估决策`}
          className="risk-panel-alert risk-panel-alert--high"
          style={{ marginBottom: 12 }}
        />
      )}

      {!hasHigh && hasMedium && (
        <Alert
          type="warning"
          showIcon
          message={`存在 ${levelCounts.medium} 项中等风险，决策可执行但需持续监控`}
          className="risk-panel-alert"
          style={{ marginBottom: 12 }}
        />
      )}

      <div className="risk-summary-bar">
        {[
          { level: 'high', label: '高风险' },
          { level: 'medium', label: '中风险' },
          { level: 'low', label: '低风险' },
        ].map(({ level, label }) => (
          <div
            key={level}
            className={`risk-summary-item${level === 'high' && levelCounts[level] ? ' risk-summary-item--high' : ''}`}
          >
            <Tag className={getRiskLevelTag(level).className}>{label}</Tag>
            <span className="risk-summary-count">{levelCounts[level] ?? 0}</span>
          </div>
        ))}
      </div>

      <Table
        rowKey={(r) => r.riskType}
        columns={columns}
        dataSource={riskList}
        pagination={false}
        size="small"
        className="risk-table"
        expandable={{
          expandedRowRender: (record) => (
            <div className="risk-expand-detail">
              <div className="risk-section">
                <div className="risk-section-label">风险解释</div>
                <DisplayParagraphs children={record.explanation} />
              </div>
              <div className="risk-section">
                <div className="risk-section-label">缓解建议</div>
                <DisplayParagraphs children={record.mitigation} />
              </div>
            </div>
          ),
          rowExpandable: () => true,
        }}
        rowClassName={(record) => `risk-row risk-row--${record.level}`}
      />
        </>
      )}
    </>
  )

  if (bare) return content

  return (
    <TerminalCard
      title="风控层：风险管理评估"
      subtitle="Risk Control Layer"
      extra="Risk Review"
    >
      {content}
    </TerminalCard>
  )
}

export default RiskPanel
