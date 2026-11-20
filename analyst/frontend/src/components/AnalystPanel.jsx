import { useMemo } from 'react'
import { TeamOutlined } from '@ant-design/icons'
import TerminalCard from './TerminalCard'
import AnalystCard from './AnalystCard'

function AnalystPanel({ analysts = [], routingWeights = [], routerWeights }) {
  const weights = routingWeights?.length ? routingWeights : (routerWeights ?? [])
  const analystList = Array.isArray(analysts) ? analysts : []

  const { weightMap, topAnalystId } = useMemo(() => {
    if (!weights.length) {
      return { weightMap: {}, topAnalystId: undefined }
    }
    const map = Object.fromEntries(weights.map((w) => [w.analystId, w.finalWeight]))
    const max = Math.max(...weights.map((w) => w.finalWeight ?? 0), 0)
    const topId = weights.find((w) => w.finalWeight === max)?.analystId
    return { weightMap: map, topAnalystId: topId }
  }, [weights])

  return (
    <TerminalCard
      title="感知层：多分析师研判"
      subtitle="Perception Layer"
      extra="5 Analysts"
      icon={<TeamOutlined />}
      accent="cyan"
    >
      <div className="analyst-grid analyst-grid--enhanced">
        {analystList.length ? (
          analystList.map((analyst, index) => (
            <AnalystCard
              key={analyst?.id ?? `analyst-${index}`}
              analyst={analyst}
              finalWeight={weightMap[analyst?.id]}
              isTopWeight={analyst?.id === topAnalystId}
            />
          ))
        ) : (
          <div className="cockpit-placeholder-body">暂无分析师数据</div>
        )}
      </div>
    </TerminalCard>
  )
}

export default AnalystPanel
