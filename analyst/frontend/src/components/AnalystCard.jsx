import { useState } from 'react'
import { Button, Progress, Tag } from 'antd'
import {
  BankOutlined,
  CrownOutlined,
  FileSearchOutlined,
  GlobalOutlined,
  LineChartOutlined,
  NotificationOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import AnalystReportModal from './AnalystReportModal'
import {
  formatWeight,
  getSignalCardClass,
  getSignalTag,
} from '@/utils/signalUtils'
import { cleanDisplayText } from '@/utils/displayTextUtils'

const ANALYST_ICONS = {
  market: LineChartOutlined,
  news: NotificationOutlined,
  industry: GlobalOutlined,
  company: BankOutlined,
  momentum: ThunderboltOutlined,
}

const DATA_SOURCE_LABELS = {
  market: '技术指标',
  news: '新闻舆情',
  industry: '行业景气度',
  company: '公司基本面',
  momentum: '相关股票动量',
}

function AnalystCard({ analyst, finalWeight, isTopWeight = false }) {
  const [modalOpen, setModalOpen] = useState(false)

  if (!analyst || typeof analyst !== 'object') {
    return null
  }

  const signal = getSignalTag(analyst?.signal ?? 'neutral')
  const cardClass = getSignalCardClass(analyst?.signal ?? 'neutral')
  const Icon = ANALYST_ICONS[analyst?.id] ?? LineChartOutlined
  const dataLabel = DATA_SOURCE_LABELS[analyst?.id] ?? analyst?.dataUsed?.[0] ?? '--'
  const confidence = typeof analyst?.confidence === 'number' ? analyst.confidence : 0
  const summaryText = cleanDisplayText(analyst?.summary) || '--'
  const summaryPreview =
    summaryText.length > 72 ? `${summaryText.slice(0, 72)}…` : summaryText

  return (
    <>
      <div
        className={`analyst-card analyst-card--enhanced ${cardClass}${
          isTopWeight ? ' analyst-card--top-weight' : ''
        }`}
      >
        {isTopWeight && (
          <div className="analyst-top-badge">
            <CrownOutlined /> Top Contributor
          </div>
        )}

        <div className="analyst-card-header">
          <div className="analyst-card-icon-wrap">
            <Icon className="analyst-card-icon" />
          </div>
          <div className="analyst-card-titles">
            <div className="analyst-name">{analyst?.name ?? '--'}</div>
            <div className="analyst-role">{analyst?.role ?? '--'}</div>
          </div>
          <Tag className={signal.className}>{signal.label}</Tag>
        </div>

        <Tag className="tag-neutral analyst-data-tag">{dataLabel}</Tag>

        <div className="analyst-card-metrics">
          <div className="analyst-metric">
            <span className="analyst-metric-label">置信度</span>
            <span className="analyst-metric-value">{formatWeight(confidence)}</span>
          </div>
          {finalWeight != null && (
            <div className={`analyst-metric${isTopWeight ? ' analyst-metric--top' : ''}`}>
              <span className="analyst-metric-label">路由权重</span>
              <span className="analyst-metric-value">{formatWeight(finalWeight)}</span>
            </div>
          )}
        </div>

        <Progress
          percent={Math.round(confidence * 100)}
          size="small"
          showInfo={false}
          strokeColor={
            analyst?.signal === 'bullish'
                ? { from: '#e93030', to: '#ff7875' }
                : analyst?.signal === 'bearish'
                  ? { from: '#00b578', to: '#52c41a' }
                  : { from: '#737373', to: '#a8a8a8' }
          }
          className="analyst-card-progress"
        />

        <p className="analyst-summary">{summaryPreview}</p>

        <Button
          type="link"
          icon={<FileSearchOutlined />}
          className="analyst-card-btn"
          onClick={() => setModalOpen(true)}
        >
          查看详情
        </Button>
      </div>

      <AnalystReportModal
        analyst={analyst}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </>
  )
}

export default AnalystCard
