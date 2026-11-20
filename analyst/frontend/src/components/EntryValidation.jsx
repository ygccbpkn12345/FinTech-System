import { useEffect, useState } from 'react'
import { Alert, Button, Modal, Space, Typography } from 'antd'
import client from '@/api/analysisApi'

const portfolioUrl = import.meta.env.VITE_FINPORTFOLIO_UI_URL || 'http://127.0.0.1:5174/'
const modes = [
  ['single', '一次买入'],
  ['staged', '分两批买入'],
]

function percent(value) {
  return Number.isFinite(value) ? (value * 100).toFixed(2) + '%' : '—'
}

export default function EntryValidation({ taskId }) {
  const [comparison, setComparison] = useState(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const path = '/api/analyze/' + encodeURIComponent(taskId) + '/entry-validation'

  useEffect(() => {
    const controller = new AbortController()
    let timer
    async function read() {
      try {
        const next = await client.get(path, { signal: controller.signal })
        if (controller.signal.aborted) return
        setComparison(next)
        setError('')
        if (next.status === 'running') timer = setTimeout(read, 1500)
      } catch (err) {
        if (!controller.signal.aborted) setError(err.message)
      }
    }
    read()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [path, refresh])

  async function submit() {
    setSubmitting(true)
    setError('')
    try {
      const next = await client.post(path)
      setComparison(next)
      setConfirming(false)
      setRefresh((value) => value + 1)
    } catch (err) {
      setError(err.message)
      setConfirming(false)
    } finally {
      setSubmitting(false)
    }
  }

  const plan = comparison?.plan
  const status = comparison?.status
  const result = comparison?.results
  const failed = status === 'failed' || status === 'incomplete'
  const canSubmit = plan && (status === 'idle' || failed)

  return (
    <section className="entry-validation" aria-label="买入方式历史对比">
      <Typography.Text strong>买入方式历史对比</Typography.Text>
      {plan?.analysis_mode === 'mock' && (
        <Typography.Text type="secondary">演示分析信号 · 回测使用本地历史行情</Typography.Text>
      )}
      {error && <Alert type="error" showIcon message={error} />}
      {failed && <Alert type="warning" showIcon message={comparison.message} />}
      {status === 'running' && <Typography.Text type="secondary" role="status">正在运行两种买入方式…</Typography.Text>}
      {!comparison && !error && <Typography.Text type="secondary" role="status">正在读取回测状态…</Typography.Text>}
      {canSubmit && (
        <Button type="primary" block onClick={() => setConfirming(true)}>
          {failed ? '继续验证' : '验证买入策略'}
        </Button>
      )}
      {error && !canSubmit && (
        <Button block onClick={() => { setError(''); setRefresh((value) => value + 1) }}>
          重新查看验证状态
        </Button>
      )}
      {status === 'completed' && (
        <>
          <Typography.Text type="secondary">
            {result.single.window_start} 至 {result.single.window_end}
          </Typography.Text>
          <table className="entry-validation-table">
            <thead><tr><th scope="col">买入方式</th><th scope="col">净收益</th><th scope="col">最大回撤</th></tr></thead>
            <tbody>
              {modes.map(([key, label]) => (
                <tr key={key}>
                  <th scope="row">
                    <a href={portfolioUrl.replace(/\/?$/, '/') + '#/backtest?experiment=' +
                      encodeURIComponent(result[key].experiment_id)} target="_blank" rel="noreferrer">
                      {label}
                    </a>
                  </th>
                  <td>{percent(result[key].net_return)}</td>
                  <td>{percent(Math.abs(result[key].max_drawdown))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Typography.Text type="secondary">
            按 {percent(plan.cost_pct)} 成交费率计算。单个窗口仅用于观察这段历史中的差异。
          </Typography.Text>
        </>
      )}
      {plan && (
        <Modal title="确认历史对比规则" open={confirming} onOk={submit}
          onCancel={() => setConfirming(false)} okText="开始验证" cancelText="取消"
          confirmLoading={submitting} closable={!submitting} maskClosable={!submitting}>
          <Space direction="vertical" size="small">
            <Typography.Text>{plan.symbol} · 使用 {plan.cutoff_date} 之前最近 {plan.window_sessions} 条日线</Typography.Text>
            <Typography.Text>一次买入在第 1 日开盘投入全部计划资金。</Typography.Text>
            <Typography.Text>
              分两批买入在第 1 日和第 {plan.second_entry_session} 日开盘各投入一半。
            </Typography.Text>
            <Typography.Text>
              两种方式均投入起始资金的 {percent(plan.position_ratio)}，在第 {plan.window_sessions} 日收盘卖出，
              按每笔成交额收取 {percent(plan.cost_pct)} 费用。
            </Typography.Text>
            <Typography.Text type="secondary">采用日线开收盘价模拟成交，允许小数股。</Typography.Text>
          </Space>
        </Modal>
      )}
    </section>
  )
}

