// 组合配置：股票权重时间序列、行业配置、预算/非负约束可视化。
// 权重一律关联真实标的代码（ticker 或论文原始位置索引，由 asset_label_mode 标注）。
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { Link, useHashRoute } from '../../router';
import {
  Alert, DataTable, EmptyState, ErrorText, Loading, Panel, fmtPct,
} from '../../components/ui';
import { WeightsStackedChart } from '../../components/charts';
import type { ExperimentSummary, PortfolioResult } from '../../types';

export default function PortfolioAnalysis() {
  const route = useHashRoute();
  const experiments = useApi<ExperimentSummary[]>(() => api.getExperiments(), []);
  const [expId, setExpId] = useState('');
  const [dateIdx, setDateIdx] = useState<number>(-1);

  useEffect(() => {
    const q = route.query.get('experiment');
    if (q) setExpId(q);
  }, [route]);

  const done = (experiments.data ?? []).filter((e) => e.status === 'SUCCEEDED');
  const result = useApi<PortfolioResult | null>(
    () => (expId ? api.getResult(expId) : Promise.resolve(null)),
    [expId],
  );
  const r = result.data;

  useEffect(() => { setDateIdx(-1); }, [expId]);

  const idx = dateIdx >= 0 && r && dateIdx < r.dates.length ? dateIdx : (r ? r.dates.length - 1 : -1);

  // 当前选中日期的权重排序
  const rows = useMemo(() => {
    if (!r || !r.weights_available || idx < 0) return [];
    const sw = r.stock_weights[idx] ?? {};
    return Object.entries(sw)
      .map(([code, w]) => ({ code, weight: w }))
      .sort((a, b) => b.weight - a.weight);
  }, [r, idx]);

  const budget = rows.length ? rows.reduce((s, x) => s + x.weight, 0) + (r && idx >= 0 ? (r.cash_weights[idx] ?? 0) : 0) : null;

  return (
    <>
      <div className="heading">
        <div>
          <h2>组合配置</h2>
          <p className="sub">组合权重结构与行业配置（预算约束 |Σw + 现金 − 1| ≤ 0.005，权重非负）</p>
        </div>
        <select value={expId} onChange={(e) => setExpId(e.target.value)} data-testid="select-portfolio-experiment">
          <option value="">— 选择已完成实验 —</option>
          {done.map((e) => (
            <option key={e.experiment_id} value={e.experiment_id}>
              {e.name}（{e.algorithm_id ?? 'import'}）
            </option>
          ))}
        </select>
      </div>

      {!expId && <EmptyState>请选择实验以查看组合权重</EmptyState>}
      {expId && result.loading && <Loading />}
      {result.error && <ErrorText error={result.error} />}

      {r && !r.weights_available && (
        <Alert kind="warn">
          该结果为 returns-only 导入（仅收益序列，无逐日权重），无法展示组合配置。
          可 <Link className="btn-link" to={`/backtest?experiment=${r.experiment_id}`}>查看其净值曲线 →</Link>
        </Alert>
      )}

      {r && r.weights_available && (
        <>
          <Alert kind="info">
            标的标签模式：<strong>{r.asset_label_mode === 'ticker' ? '真实代码' : '论文原始位置索引'}</strong>
            {r.asset_label_mode === 'position_index' && '（论文输出为持仓位置，适配层已按交易日排序映射到代码）'}
          </Alert>

          <Panel title="股票权重演化（堆叠）" subtitle="每日收盘后的目标权重（含现金腿）">
            <WeightsStackedChart dates={r.dates} weights={r.stock_weights} cashWeights={r.cash_weights} />
          </Panel>

          <Panel
            title="逐日权重明细"
            subtitle={idx >= 0 ? `${r.dates[idx]} 的持仓` : ''}
            actions={
              <select value={idx} onChange={(e) => setDateIdx(Number(e.target.value))}>
                {r.dates.map((d, i) => (
                  <option key={d} value={i}>{d}</option>
                ))}
              </select>
            }
          >
            <div className="cards">
              <div className="metric">
                <div className="m-label">持仓标的数</div>
                <div className="m-value">{rows.length}</div>
              </div>
              <div className="metric">
                <div className="m-label">股票仓位合计</div>
                <div className="m-value">{fmtPct(rows.reduce((s, x) => s + x.weight, 0))}</div>
              </div>
              <div className="metric">
                <div className="m-label">现金比例</div>
                <div className="m-value">{fmtPct(r.cash_weights[idx] ?? 0)}</div>
              </div>
              <div className="metric">
                <div className="m-label">预算偏差</div>
                <div className={`m-value ${budget !== null && Math.abs(budget - 1) <= 0.005 ? 'ok-text' : 'bad-text'}`}>
                  {budget !== null ? `${((budget - 1) * 100).toFixed(3)}%` : '—'}
                </div>
                <div className="m-hint">容差 ±0.5%（后端已强校验）</div>
              </div>
            </div>

            <DataTable
              columns={[
                { key: 'code', header: '标的代码', render: (x) => <code>{x.code}</code> },
                { key: 'w', header: '权重', render: (x) => (
                  <span className={x.weight < 0 ? 'bad-text' : ''}>{fmtPct(x.weight)}</span>
                ) },
                {
                  key: 'bar', header: '占比', width: '30%', render: (x) => (
                    <div className="wbar"><div className="wbar-fill" style={{ width: `${Math.max(0, Math.min(1, x.weight)) * 100}%` }} /></div>
                  ),
                },
              ]}
              rows={rows}
              empty="该日期无权重数据"
            />
            {r.industry_weights && idx >= 0 && (
              <>
                <h4>行业层资金权重（{r.dates[idx]}）</h4>
                <div className="tag-cloud">
                  {Object.entries(r.industry_weights[idx] ?? {}).sort((a, b) => b[1] - a[1]).map(([ind, w]) => (
                    <span key={ind} className="pill subtle">行业 {ind}：{fmtPct(w)}</span>
                  ))}
                </div>
                <div className="param-desc">
                  HMMP 类分层算法的最终权重 = 行业资金权重 × 行业内条件权重；此处两层数据均来自标准化结果。
                </div>
              </>
            )}
          </Panel>
        </>
      )}
    </>
  );
}
