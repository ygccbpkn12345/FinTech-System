// 回测分析：查看已完成实验的标准结果——净值曲线（毛/净）、回撤、换手、指标与口径假设
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { useHashRoute } from '../../router';
import {
  Alert, DataTable, EmptyState, ErrorText, Loading, MetricCard, Panel, fmtNum, fmtPct,
} from '../../components/ui';
import { DrawdownChart, TurnoverChart, WealthChart } from '../../components/charts';
import type { ExperimentSummary, PortfolioResult } from '../../types';

const MODE_LABEL: Record<string, string> = {
  paper_original: '论文原始口径（paper_original）',
  unified_rebalance: '统一定期再平衡（unified_rebalance）',
};

export default function Backtest() {
  const route = useHashRoute();
  const experiments = useApi<ExperimentSummary[]>(() => api.getExperiments(), [], 5000);
  const [expId, setExpId] = useState<string>('');

  useEffect(() => {
    const q = route.query.get('experiment');
    if (q) setExpId(q);
  }, [route]);

  const done = (experiments.data ?? []).filter((e) => e.status === 'SUCCEEDED');
  const result = useApi<PortfolioResult | null>(
    () => (expId ? api.getResult(expId) : Promise.resolve(null)),
    [expId],
  );

  const exp = expId ? done.find((e) => e.experiment_id === expId) : null;
  const r = result.data;

  return (
    <>
      <div className="heading">
        <div>
          <h2>回测分析</h2>
          <p className="sub">统一标准结果（StandardPortfolioResult）：原始与扣费收益分离、口径假设显式声明</p>
        </div>
        <select value={expId} onChange={(e) => setExpId(e.target.value)} data-testid="select-experiment">
          <option value="">— 选择已完成实验 —</option>
          {done.map((e) => (
            <option key={e.experiment_id} value={e.experiment_id}>
              {e.name}（{e.algorithm_id ?? 'import'} · {e.experiment_id.slice(0, 12)}…）
            </option>
          ))}
        </select>
      </div>

      {!expId && <EmptyState>请选择一个已成功的实验查看回测结果</EmptyState>}
      {expId && result.loading && <Loading />}
      {result.error && <ErrorText error={result.error} />}
      {expId && !result.loading && !r && <EmptyState>该实验没有可用的标准结果</EmptyState>}

      {r && (
        <>
          <Alert kind="info">
            回测模式：<strong>{MODE_LABEL[r.backtest_mode] ?? r.backtest_mode}</strong>
            {' · '}收益序列：<strong>{r.cost_included ? '含交易费用' : '主收益序列费前'}</strong>
            {r.net_daily_returns ? ' · 另提供独立扣费序列（虚线）' : ''}
            {' · '}年化假设 {r.metric_assumptions.trading_days_per_year} 交易日 / 无风险利率 {fmtPct(r.metric_assumptions.risk_free_rate, 1)}
          </Alert>

          <div className="cards">
            <MetricCard
              label="累计收益"
              value={<span className={(r.metrics.cumulative_return ?? 0) >= 0 ? 'pos' : 'neg'}>{fmtPct(r.metrics.cumulative_return)}</span>}
              hint={`${r.metrics.days} 个交易日`}
            />
            <MetricCard
              label="年化收益（几何）"
              value={<span className={(r.metrics.annualized_return ?? 0) >= 0 ? 'pos' : 'neg'}>{fmtPct(r.metrics.annualized_return)}</span>}
              hint={`wealth^(252/n)-1`}
            />
            <MetricCard label="年化波动率" value={fmtPct(r.metrics.annualized_volatility)} />
            <MetricCard
              label="Sharpe"
              value={fmtNum(r.metrics.sharpe_ratio, 2)}
              hint={r.metrics.sharpe_ratio === null ? '零波动序列，指标未定义' : 'rf=0'}
            />
            <MetricCard
              label="最大回撤"
              value={<span className="neg">{fmtPct(r.metrics.max_drawdown)}</span>}
              hint={`Calmar ${fmtNum(r.metrics.calmar_ratio, 2)}`}
            />
            <MetricCard
              label="平均单边换手"
              value={fmtPct(r.metrics.avg_turnover)}
              hint={`现金均值 ${fmtPct(r.metrics.avg_cash_ratio)}`}
            />
          </div>

          <Panel title="净值曲线" subtitle={`${r.algorithm_id} · 数据集 ${r.dataset_id} · ${r.dates[0]} ~ ${r.dates[r.dates.length - 1]}`}>
            <WealthChart
              dates={r.dates}
              values={r.net_daily_returns ? wealthSeries(r.daily_returns) : r.portfolio_values}
              netValues={r.net_daily_returns ? wealthSeries(r.net_daily_returns) : undefined}
              height={340}
            />
            {r.net_daily_returns && (
              <div className="chart-note">实线 = 费前净值；虚线 = 扣费后净值</div>
            )}
          </Panel>

          <div className="grid2">
            <Panel title={r.net_daily_returns || r.cost_included ? '回撤序列（扣费后）' : '回撤序列'}>
              {r.portfolio_values.length > 1 ? (
                <DrawdownChart dates={r.dates} drawdown={drawdownOf(r)} />
              ) : <EmptyState>序列过短</EmptyState>}
            </Panel>
            <Panel title="单边换手率">
              {r.turnover && r.turnover.length ? (
                <TurnoverChart dates={r.dates} turnover={r.turnover} />
              ) : <EmptyState>该结果未提供换手序列（returns-only 导入）</EmptyState>}
            </Panel>
          </div>

          {r.notes.length > 0 && (
            <Panel title="结果口径说明（来自插件 / 导入器）">
              <ul className="notes-list">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </Panel>
          )}

          <div className="grid2">
            <Panel title="全部指标">
              <DataTable
                columns={[
                  { key: 'k', header: '指标', render: (row) => <code>{row.k}</code> },
                  { key: 'v', header: '值', render: (row) => row.pct !== undefined
                    ? (row.signed
                      ? <span className={row.pct >= 0 ? 'pos' : 'neg'}>{fmtPct(row.pct)}</span>
                      : fmtPct(row.pct))
                    : fmtNum(row.v) },
                ]}
                rows={Object.entries(r.metrics).map(([k, v]) => ({
                  k,
                  v: typeof v === 'number' ? v : null,
                  pct: typeof v === 'number' && /return|volatility|drawdown|turnover|cash/.test(k) ? v : undefined,
                  signed: typeof v === 'number' && /return|drawdown/.test(k),
                }))}
              />
            </Panel>
            <Panel title="工件与配置">
              <h4>输出工件</h4>
              {r.artifacts.length ? (
                <ul className="file-list">
                  {r.artifacts.map((a) => (
                    <li key={a.path}><code>{a.name}</code> <span className="muted">{a.path}</span></li>
                  ))}
                </ul>
              ) : <EmptyState>无工件</EmptyState>}
              <h4>运行配置</h4>
              <pre className="logbox small-text">{JSON.stringify(r.configuration, null, 2)}</pre>
              {exp?.params && (
                <>
                  <h4>实验参数</h4>
                  <pre className="logbox small-text">{JSON.stringify(exp.params, null, 2)}</pre>
                </>
              )}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

function wealthSeries(returns: number[]): number[] {
  const w: number[] = [];
  let v = 1.0;
  for (const ret of returns) { v *= 1 + ret; w.push(v); }
  return w;
}

function drawdownOf(r: PortfolioResult): number[] {
  const w: number[] = [];
  let v = 1.0;
  let peak = 1.0;
  for (const ret of r.net_daily_returns ?? r.daily_returns) {
    v *= 1 + ret;
    peak = Math.max(peak, v);
    w.push(v / peak - 1);
  }
  return w;
}
