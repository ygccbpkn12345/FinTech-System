// 策略对比：多选实验 → /api/results/compare。后端给出公平性检查（数据集/窗口/股票池/回测模式/费率）
import { useEffect, useState } from 'react';
import { GitCompare } from 'lucide-react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import {
  Alert, DataTable, EmptyState, ErrorText, Loading, Panel, fmtNum, fmtPct,
} from '../../components/ui';
import { CompareChart } from '../../components/charts';
import type { CompareResponse, ExperimentSummary } from '../../types';

const METRIC_ROWS: { key: string; label: string; pct?: boolean }[] = [
  { key: 'cumulative_return', label: '累计收益', pct: true },
  { key: 'annualized_return', label: '年化收益（几何）', pct: true },
  { key: 'annualized_volatility', label: '年化波动率', pct: true },
  { key: 'sharpe_ratio', label: 'Sharpe（rf=0）' },
  { key: 'sortino_ratio', label: 'Sortino' },
  { key: 'max_drawdown', label: '最大回撤', pct: true },
  { key: 'calmar_ratio', label: 'Calmar' },
  { key: 'avg_turnover', label: '平均单边换手', pct: true },
  { key: 'days', label: '交易日数' },
];

export default function StrategyComparison() {
  const experiments = useApi<ExperimentSummary[]>(() => api.getExperiments(), []);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const [cmpError, setCmpError] = useState<string | null>(null);
  const [cmp, setCmp] = useState<CompareResponse | null>(null);

  const done = (experiments.data ?? []).filter((e) => e.status === 'SUCCEEDED');

  useEffect(() => { setCmp(null); setCmpError(null); }, [selected.join(',')]);

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const onCompare = async () => {
    setComparing(true);
    setCmpError(null);
    setCmp(null);
    try {
      setCmp(await api.compare(selected));
    } catch (e) {
      setCmpError(e instanceof Error ? e.message : String(e));
    } finally {
      setComparing(false);
    }
  };

  return (
    <>
      <div className="heading">
        <div>
          <h2>策略对比</h2>
          <p className="sub">跨算法净值与指标对比；口径不一致时后端会给出公平性警告</p>
        </div>
        <button
          className="primary"
          disabled={selected.length < 2 || comparing}
          onClick={onCompare}
          data-testid="compare-btn"
        >
          <GitCompare size={14} /> {comparing ? '对比中…' : `对比（已选 ${selected.length}）`}
        </button>
      </div>

      <Panel title="选择要对比的实验（≥ 2 个）" subtitle="勾选已完成实验；比较前请留意数据集与回测模式是否一致">
        {done.length === 0 && <EmptyState>暂无已完成实验</EmptyState>}
        {done.length > 0 && (
          <DataTable
            columns={[
              {
                key: 'chk', header: '', render: (e) => (
                  <input
                    type="checkbox"
                    checked={selected.includes(e.experiment_id)}
                    onChange={() => toggle(e.experiment_id)}
                  />
                ),
              },
              { key: 'name', header: '实验', render: (e) => e.name },
              { key: 'algo', header: '算法', render: (e) => <code>{e.algorithm_id ?? 'import'}</code> },
              { key: 'ds', header: '数据集', render: (e) => <code>{e.dataset_id ?? '—'}</code> },
              { key: 'mode', header: '回测模式', render: (e) => e.backtest_mode ?? '—' },
              {
                key: 'ret', header: '累计收益', render: (e) => {
                  const v = e.result_summary?.cumulative_return;
                  return v === null || v === undefined ? '—' : <span className={v >= 0 ? 'pos' : 'neg'}>{fmtPct(v)}</span>;
                },
              },
              { key: 'sr', header: 'Sharpe', render: (e) => fmtNum(e.result_summary?.sharpe_ratio ?? null, 2) },
            ]}
            rows={done}
          />
        )}
      </Panel>

      {cmpError && <Alert kind="error">对比失败：{cmpError}</Alert>}

      {cmp && (
        <>
          {!cmp.fair && cmp.warnings.length > 0 && (
            <Alert kind="warn">
              <strong>公平性警告</strong>（以下差异可能使对比不具说服力）：
              <ul>{cmp.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </Alert>
          )}
          {cmp.fair && <Alert kind="success">各实验口径一致（数据集 / 窗口 / 回测模式相同），对比公平</Alert>}

          <Panel title="净值曲线对比" subtitle="初始净值 = 1.0；不同数据集的曲线区间可能错开">
            <CompareChart
              series={cmp.experiments.map((e) => ({ name: `${e.name}（${e.algorithm_id}）`, dates: e.dates, values: e.portfolio_values }))}
            />
          </Panel>

          <Panel title="指标对比" subtitle="全部指标同口径计算：252 交易日年化、rf=0、几何复利">
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>指标</th>
                    {cmp.experiments.map((e) => <th key={e.experiment_id}>{e.name}<div className="th-sub"><code>{e.algorithm_id}</code></div></th>)}
                  </tr>
                </thead>
                <tbody>
                  {METRIC_ROWS.map((row) => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      {cmp.experiments.map((e) => {
                        const v = e.metrics[row.key];
                        return (
                          <td key={e.experiment_id} className={
                            typeof v !== 'number' ? ''
                              : row.key === 'max_drawdown' ? 'neg'
                                : /return/.test(row.key) ? (v >= 0 ? 'pos' : 'neg')
                                  : ''
                          }>
                            {v === null || v === undefined ? '—' : row.pct ? fmtPct(v) : fmtNum(v, row.key === 'days' ? 0 : 3)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="param-desc">
              各实验口径：{cmp.experiments.map((e) => `${e.algorithm_id}=${e.metric_assumptions.trading_days_per_year}日年化/rf=${e.metric_assumptions.risk_free_rate}`).join('；')}
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
