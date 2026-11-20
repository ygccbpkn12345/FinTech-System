// 股票筛选：查看 stock_selection 能力实验输出的逐日筛选名单（打分 / 排名 / 入选组合）
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { useHashRoute } from '../../router';
import {
  Alert, DataTable, EmptyState, ErrorText, Loading, Panel,
} from '../../components/ui';
import type { ExperimentSummary, PortfolioResult } from '../../types';

type SelectionDay = NonNullable<PortfolioResult['stock_selection']>[number];

export default function StockSelection() {
  const route = useHashRoute();
  const experiments = useApi<ExperimentSummary[]>(() => api.getExperiments(), []);
  const [expId, setExpId] = useState('');

  useEffect(() => {
    const q = route.query.get('experiment');
    if (q) setExpId(q);
  }, [route]);

  const candidates = (experiments.data ?? []).filter((e) => e.status === 'SUCCEEDED');
  const result = useApi<PortfolioResult | null>(
    () => (expId ? api.getResult(expId) : Promise.resolve(null)),
    [expId],
  );
  const r = result.data;
  const selection = r?.stock_selection;
  const [dayIdx, setDayIdx] = useState(0);

  useEffect(() => { setDayIdx(0); }, [expId]);
  const day: SelectionDay | undefined = selection?.length
    ? selection[Math.min(dayIdx, selection.length - 1)]
    : undefined;

  return (
    <>
      <div className="heading">
        <div>
          <h2>股票筛选</h2>
          <p className="sub">算法插件 stock_selection 能力的输出：逐日打分排名与入选名单（如 ASACPL 的 HLB-AS 预筛选）</p>
        </div>
        <select value={expId} onChange={(e) => setExpId(e.target.value)} data-testid="select-selection-experiment">
          <option value="">— 选择已完成实验 —</option>
          {candidates.map((e) => (
            <option key={e.experiment_id} value={e.experiment_id}>
              {e.name}（{e.algorithm_id ?? 'import'}）
            </option>
          ))}
        </select>
      </div>

      {!expId && <EmptyState>请选择实验以查看筛选结果</EmptyState>}
      {expId && result.loading && <Loading />}
      {result.error && <ErrorText error={result.error} />}

      {r && !selection && (
        <Alert kind="warn">
          实验 {r.experiment_id} 的结果不含股票筛选数据（对应算法未声明 stock_selection 能力，
          或该次运行未产出筛选工件）。
        </Alert>
      )}

      {selection && day && (
        <>
          <div className="cards">
            <div className="metric">
              <div className="m-label">筛选交易日数</div>
              <div className="m-value">{selection.length}</div>
            </div>
            <div className="metric">
              <div className="m-label">当前日期</div>
              <div className="m-value small-text">{day.date}</div>
            </div>
            <div className="metric">
              <div className="m-label">候选池大小</div>
              <div className="m-value">{day.ranked.length}</div>
            </div>
            <div className="metric">
              <div className="m-label">入选组合（top_k）</div>
              <div className="m-value">{day.top_k.length}</div>
            </div>
          </div>

          <Panel
            title="逐日筛选明细"
            actions={
              <select value={dayIdx} onChange={(e) => setDayIdx(Number(e.target.value))}>
                {selection.map((s, i) => (
                  <option key={s.date} value={i}>{s.date}</option>
                ))}
              </select>
            }
          >
            <DataTable
              columns={[
                {
                  key: 'rank', header: '排名', render: (x) => {
                    const rank = x.rank ?? x.i + 1;
                    return day.top_k.includes(x.code)
                      ? <strong className="ok-text">#{rank} ✓ 入选</strong>
                      : <span className="muted">#{rank}</span>;
                  },
                },
                { key: 'code', header: '标的代码', render: (x) => <code>{x.code}</code> },
                { key: 'score', header: '筛选得分', render: (x) => (x.score !== undefined ? x.score.toFixed(6) : '—') },
                {
                  key: 'in', header: '进入组合', render: (x) =>
                    day.top_k.includes(x.code) ? <span className="pill badge-ok">是</span> : <span className="pill subtle">否</span>,
                },
              ]}
              rows={day.ranked.map((item, i) => ({ ...item, i }))}
            />
          </Panel>
        </>
      )}
    </>
  );
}
