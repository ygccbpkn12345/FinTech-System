import { useMemo } from 'react'
import { Table, Tag } from 'antd'
import { ArrowRightOutlined, CrownOutlined, PlusOutlined } from '@ant-design/icons'
import TerminalCard from './TerminalCard'
import RouterWeightChart from './RouterWeightChart'
import { formatWeight } from '@/utils/signalUtils'

function RouterWeightPanel({ routingWeights = [], routerWeights }) {
  const weights = routingWeights?.length ? routingWeights : (routerWeights ?? [])

  const maxFinalWeight = useMemo(
    () => Math.max(...weights.map((w) => w.finalWeight ?? 0), 0),
    [weights],
  )

  const topAnalystId = useMemo(
    () => weights.find((w) => w.finalWeight === maxFinalWeight)?.analystId,
    [weights, maxFinalWeight],
  )

  const columns = [
    {
      title: '分析师',
      dataIndex: 'analystName',
      key: 'analystName',
      width: 100,
      render: (name, record) => (
        <span className="weight-analyst-name">
          {record.analystId === topAnalystId && <CrownOutlined className="weight-top-icon" />}
          {(name ?? '--').replace('分析师', '')}
        </span>
      ),
    },
    {
      title: '置信权重',
      dataIndex: 'confidenceWeight',
      key: 'confidenceWeight',
      align: 'right',
      width: 80,
      render: (v) => <span className="weight-cell weight-cell-confidence">{formatWeight(v)}</span>,
    },
    {
      title: 'RAG权重',
      dataIndex: 'historicalWeight',
      key: 'historicalWeight',
      align: 'right',
      width: 80,
      render: (v) => <span className="weight-cell weight-cell-historical">{formatWeight(v)}</span>,
    },
    {
      title: '最终权重',
      dataIndex: 'finalWeight',
      key: 'finalWeight',
      align: 'right',
      width: 80,
      render: (v, record) => (
        <span
          className={`weight-cell weight-cell-final${
            record.analystId === topAnalystId ? ' weight-cell-final--top' : ''
          }`}
        >
          {formatWeight(v)}
        </span>
      ),
    },
  ]

  return (
    <TerminalCard
      title="路由层：动态专家权重"
      subtitle="Routing Layer"
      extra="Weight Matrix"
    >
      <div className="router-formula router-formula--compact">
        <Tag className="router-formula-tag router-formula-confidence">当前置信度</Tag>
        <PlusOutlined className="router-formula-op" />
        <Tag className="router-formula-tag router-formula-rag">历史 RAG 检索</Tag>
        <ArrowRightOutlined className="router-formula-op" />
        <Tag className="router-formula-tag router-formula-final">最终专家权重</Tag>
      </div>

      <div className="router-chart-block">
        <RouterWeightChart routingWeights={weights} horizontal />
      </div>

      {weights.length ? (
        <Table
          rowKey={(record, index) => record.analystId ?? `weight-${index}`}
          columns={columns}
          dataSource={weights}
        pagination={false}
        size="small"
        className="weight-table router-weight-table"
        rowClassName={(record) =>
          record.analystId === topAnalystId ? 'weight-row-top' : ''
        }
        />
      ) : (
        <div className="cockpit-placeholder-body">暂无路由权重数据</div>
      )}
    </TerminalCard>
  )
}

export default RouterWeightPanel
