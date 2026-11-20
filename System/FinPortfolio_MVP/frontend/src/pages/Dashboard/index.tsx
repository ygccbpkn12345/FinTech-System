// 系统概览：平台统计、运行中任务、最近实验、最新净值曲线（全部来自 /api/system/overview）
import { RefreshCw } from 'lucide-react';
import { Link } from '../../router';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { fmtPct, fmtTime, Alert, DataTable, EmptyState, ErrorText, Loading, MetricCard, Panel, StatusBadge, fmtNum } from '../../components/ui';
import { DrawdownChart, WealthChart } from '../../components/charts';
import type { ExperimentSummary } from '../../types';

export default function Dashboard() {
  const { data, loading, error, refresh } = useApi(() => api.getOverview(), [], 8000);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorText error={error} />;

  const recent: ExperimentSummary[] = data?.recent_experiments ?? [];
  const curve = data?.latest_portfolio_curve;

  return (
    <>
      <div className="heading">
        <div>
          <h2>系统概览</h2>
          <p className="sub">插件注册表、数据集与实验任务的整体状态</p>
        </div>
        <button className="outline" onClick={refresh}>
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      {(data?.plugin_scan.failed && Object.keys(data.plugin_scan.failed).length > 0) && (
        <Alert kind="warn">
          有 {Object.keys(data.plugin_scan.failed).length} 个插件目录加载失败：
          {Object.entries(data.plugin_scan.failed)
            .map(([dir, err]) => `${dir}（${String(err).slice(0, 80)}）`)
            .join('；')}
          。失败插件已隔离，不影响其他算法。
        </Alert>
      )}

      <div className="cards">
        <MetricCard label="已注册算法" value={data?.algorithms_registered ?? '—'} hint={`另有 ${data?.algorithms_failed ?? 0} 个加载失败`} />
        <MetricCard label="数据集" value={data?.datasets ?? '—'} />
        <MetricCard label="实验总数" value={data?.experiments_total ?? '—'} hint={`成功 ${data?.experiments_succeeded ?? 0} · 失败 ${data?.experiments_failed ?? 0}`} />
        <MetricCard label="运行中任务" value={data?.running_tasks.length ?? 0} tone={(data?.running_tasks.length ?? 0) > 0 ? 'positive' : 'default'} />
      </div>

      {(data?.running_tasks.length ?? 0) > 0 && (
        <Panel title="运行中的任务" subtitle="训练 / 回测子进程实时状态">
          <DataTable
            columns={[
              { key: 'name', header: '实验', render: (r) => <Link to={`/experiments?focus=${r.experiment_id}`}>{r.name}</Link> },
              { key: 'algo', header: '算法', render: (r) => <code>{r.algorithm_id}</code> },
              { key: 'status', header: '状态', render: (r) => <StatusBadge status={r.status} /> },
            ]}
            rows={data!.running_tasks}
          />
        </Panel>
      )}

      {curve ? (
        <Panel
          title="最新组合净值曲线"
          subtitle={`${curve.name}（${curve.experiment_id}）`}
          actions={<Link className="btn-link" to={`/backtest?experiment=${curve.experiment_id}`}>进入回测分析</Link>}
        >
          <div className="grid2">
            <div>
              <WealthChart dates={curve.dates} values={curve.values} />
              <div className="chart-note">累计净值（初始 = 1.0）</div>
            </div>
            <div>
              <DrawdownChart dates={curve.dates} drawdown={curve.drawdown} />
              <div className="chart-note">
                最大回撤 {fmtPct(curve.metrics.max_drawdown)} · 年化收益 {fmtPct(curve.metrics.annualized_return)} · 夏普 {fmtNum(curve.metrics.sharpe_ratio, 2)}
              </div>
            </div>
          </div>
        </Panel>
      ) : (
        <Panel title="最新组合净值曲线">
          <EmptyState>
            暂无已完成的实验结果。可先前往 <Link to="/algorithms">算法中心</Link> 查看已注册算法，
            或在 <Link to="/training">训练中心</Link> 发起一次训练 / 回测。
          </EmptyState>
        </Panel>
      )}

      <Panel
        title="最近实验"
        actions={<Link className="btn-link" to="/experiments">查看全部</Link>}
      >
        <DataTable
          columns={[
            { key: 'name', header: '名称', render: (r) => r.name },
            { key: 'algo', header: '算法', render: (r) => <code>{r.algorithm_id ?? '—'}</code> },
            { key: 'cap', header: '类型', render: (r) => r.capability ?? r.kind },
            { key: 'status', header: '状态', render: (r) => <StatusBadge status={r.status} /> },
            {
              key: 'ret', header: '累计收益', render: (r) => {
                const v = r.result_summary?.cumulative_return;
                return v === null || v === undefined ? '—' : <span className={v >= 0 ? 'pos' : 'neg'}>{fmtPct(v)}</span>;
              },
            },
            { key: 'time', header: '创建时间', render: (r) => fmtTime(r.created_at) },
          ]}
          rows={recent.slice(0, 8)}
          empty="还没有实验记录"
        />
      </Panel>
    </>
  );
}
