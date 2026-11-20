import { Progress } from 'antd'
import { ExclamationCircleOutlined, SafetyOutlined } from '@ant-design/icons'
import TerminalCard from './TerminalCard'
import { getActionTheme } from '@/utils/signalUtils'
import { cleanDisplayText } from '@/utils/displayTextUtils'
import { buildFinalDecisionDisplay } from '@/utils/finalDecisionDisplay'

function FinalDecisionCard({ decision, compact = false, riskScore }) {
  const safeDecision = decision ?? {}
  const { action, actionEn } = buildFinalDecisionDisplay(safeDecision)
  const confidence = typeof safeDecision.confidence === 'number' ? safeDecision.confidence : 0
  const compositeScore = safeDecision.compositeScore ?? '--'
  const targetHorizon = safeDecision.targetPrice?.horizon ?? '--'
  const targetLow = safeDecision.targetPrice?.low
  const targetHigh = safeDecision.targetPrice?.high
  const stopLoss = safeDecision.stopLoss
  const coreReason = cleanDisplayText(safeDecision.coreReason ?? '')
  const keyRisks = Array.isArray(safeDecision.keyRisks)
    ? safeDecision.keyRisks.map((r) => cleanDisplayText(r)).filter(Boolean)
    : []

  const theme = getActionTheme(action)
  const confidencePercent = Math.round(confidence * 100)

  if (compact) {
    return (
      <div className={`final-decision-compact ${theme.className}`}>
        <div className={`final-compact-hero ${theme.heroClass}`}>
          <div className="final-compact-action">{action}</div>
          <div className="final-compact-action-en">{actionEn}</div>
          <div className="final-compact-meta">
            <span className="final-compact-conf">置信 {confidencePercent}%</span>
          </div>
        </div>

        <div className="final-compact-grid">
          <div className="final-compact-metric">
            <div className="final-compact-metric-label">置信度</div>
            <div className="final-compact-metric-value" style={{ color: 'var(--accent-cyan)' }}>
              {confidencePercent}%
            </div>
          </div>
          <div className="final-compact-metric">
            <div className="final-compact-metric-label">风险评分</div>
            <div className="final-compact-metric-value">
              {riskScore?.score ?? '—'}
            </div>
          </div>
          <div className="final-compact-metric">
            <div className="final-compact-metric-label">持有周期</div>
            <div className="final-compact-metric-value final-compact-metric-sm">
              {targetHorizon}
            </div>
          </div>
          <div className="final-compact-metric">
            <div className="final-compact-metric-label">目标价</div>
            <div className="final-compact-metric-value final-compact-metric-sm">
              {targetLow && targetHigh ? `${targetLow}–${targetHigh}` : '--'}
            </div>
          </div>
          <div className="final-compact-metric">
            <div className="final-compact-metric-label">止损价</div>
            <div className="final-compact-metric-value final-compact-metric-sm">
              {stopLoss ? stopLoss : '--'}
            </div>
          </div>
        </div>

        <Progress
          percent={confidencePercent}
          size="small"
          strokeColor={theme.progressColor}
          showInfo={false}
          style={{ marginBottom: 10 }}
        />

        <div className="final-compact-block">
          <div className="final-compact-block-title">
            <SafetyOutlined /> 核心依据
          </div>
          <p className="final-compact-text">
            {coreReason
              ? coreReason.length > 120
                ? `${coreReason.slice(0, 120)}…`
                : coreReason
              : '--'}
          </p>
        </div>

        <div className="final-compact-block">
          <div className="final-compact-block-title">
            <ExclamationCircleOutlined /> 关键风险
          </div>
          <ul className="final-compact-risks">
            {keyRisks.length ? (
              keyRisks.slice(0, 3).map((r) => <li key={r}>{r}</li>)
            ) : (
              <li>--</li>
            )}
          </ul>
        </div>
      </div>
    )
  }

  return (
    <TerminalCard
      title="终局输出：最终投资建议"
      extra="Final Output Layer"
      className={`final-decision-card ${theme.className}`}
    >
      <div className={`final-hero ${theme.heroClass}`}>
        <div className="final-compact-action">{action}</div>
        <div className="final-compact-action-en">{actionEn}</div>
      </div>
      <div className="final-compact-grid">
        <div className="final-compact-metric">
          <div className="final-compact-metric-label">置信度</div>
          <div className="final-compact-metric-value">{confidencePercent}%</div>
        </div>
        <div className="final-compact-metric">
          <div className="final-compact-metric-label">综合评分</div>
          <div className="final-compact-metric-value">{compositeScore}</div>
        </div>
        <div className="final-compact-metric">
          <div className="final-compact-metric-label">持有周期</div>
          <div className="final-compact-metric-value final-compact-metric-sm">
            {targetHorizon}
          </div>
        </div>
      </div>
    </TerminalCard>
  )
}

export default FinalDecisionCard
