// 实验管理：全部实验列表（筛选 / 日志查看 / 取消 / 删除）+ 论文结果 CSV 上传导入
import { useEffect, useRef, useState } from 'react';
import { FileUp, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { Link, useHashRoute } from '../../router';
import {
  Alert, DataTable, EmptyState, ErrorText, Loading, Panel, StatusBadge,
  fmtDuration, fmtTime,
} from '../../components/ui';
import type { AlgorithmInfo, ExperimentSummary, TaskStatus } from '../../types';

export default function ExperimentManager() {
  const route = useHashRoute();
  const { data, loading, error, refresh } = useApi<ExperimentSummary[]>(() => api.getExperiments(), [], 5000);
  const algos = useApi<AlgorithmInfo[]>(() => api.getAlgorithms(), []);
  const [focus, setFocus] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [task, setTask] = useState<TaskStatus | null>(null);
  const [logs, setLogs] = useState('');

  useEffect(() => {
    const q = route.query.get('focus');
    if (q) setFocus(q);
  }, [route]);

  // 聚焦实验：拉取任务状态 + 日志（未结束时轮询）
  useEffect(() => {
    setTask(null);
    setLogs('');
    if (!focus) return;
    const exp = (data ?? []).find((e) => e.experiment_id === focus);
    if (!exp) return;
    let stop = false;
    const poll = async () => {
      try {
        const [st, lg] = await Promise.all([
          exp.task_id ? api.getTaskStatus(exp.task_id) : Promise.resolve(null),
          exp.task_id ? api.getTaskLogs(exp.task_id, 200) : Promise.resolve(null),
        ]);
        if (st) setTask(st);
        if (lg) setLogs(lg.log);
        if (!st || !['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(st.state)) {
          if (!stop) setTimeout(poll, 1500);
        }
      } catch { /* 忽略轮询错误 */ }
    };
    poll();
    return () => { stop = true; };
  }, [focus, data]);

  const onCancel = async (taskId: string) => {
    if (!window.confirm('确认取消该任务？')) return;
    try { await api.cancelTask(taskId); refresh(); } catch (e) { alert(e instanceof Error ? e.message : String(e)); }
  };

  const onDelete = async (id: string) => {
    if (!window.confirm('删除该实验及其结果文件？该操作不可恢复。')) return;
    try { await api.deleteExperiment(id); if (focus === id) setFocus(null); refresh(); }
    catch (e) { alert(e instanceof Error ? e.message : String(e)); }
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorText error={error} />;

  const all = data ?? [];
  const filtered = statusFilter ? all.filter((e) => e.status === statusFilter) : all;
  const focused = focus ? all.find((e) => e.experiment_id === focus) : null;

  return (
    <>
      <div className="heading">
        <div>
          <h2>实验管理</h2>
          <p className="sub">共 {all.length} 个实验（插件运行与论文结果导入统一管理）</p>
        </div>
        <div className="row-ops">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">全部状态</option>
            {['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="outline" onClick={refresh}><RefreshCw size={14} /> 刷新</button>
        </div>
      </div>

      <Panel title="实验列表">
        <DataTable
          columns={[
            { key: 'name', header: '名称', render: (e) => (
              <button className="btn-link" onClick={() => setFocus(e.experiment_id)}>{e.name}</button>
            ) },
            { key: 'algo', header: '算法', render: (e) => <code>{e.algorithm_id ?? '—'}</code> },
            { key: 'kind', header: '来源', render: (e) => (e.kind === 'import' ? '论文导入' : '插件运行') },
            { key: 'cap', header: '能力', render: (e) => e.capability ?? '—' },
            { key: 'status', header: '状态', render: (e) => <StatusBadge status={e.status} /> },
            { key: 'created', header: '创建时间', render: (e) => fmtTime(e.created_at) },
            {
              key: 'ops', header: '操作', render: (e) => (
                <div className="row-ops">
                  {e.status === 'SUCCEEDED' && (
                    <>
                      <Link className="btn-link" to={`/backtest?experiment=${e.experiment_id}`}>结果</Link>
                      <Link className="btn-link" to={`/portfolio?experiment=${e.experiment_id}`}>权重</Link>
                    </>
                  )}
                  {(e.status === 'RUNNING' || e.status === 'PENDING') && e.task_id && (
                    <button className="outline small danger" onClick={() => onCancel(e.task_id!)}>取消</button>
                  )}
                  <button className="outline small danger" onClick={() => onDelete(e.experiment_id)} title="删除">
                    <Trash2 size={12} />
                  </button>
                </div>
              ),
            },
          ]}
          rows={filtered}
          empty="暂无实验。可在训练中心发起，或在下方导入论文结果 CSV"
        />
      </Panel>

      {focused && (
        <Panel title={`实验详情 · ${focused.name}`} subtitle={<code>{focused.experiment_id}</code>}
          actions={task && <StatusBadge status={task.state} />}>
          <dl className="kv">
            <dt>算法</dt><dd>{focused.algorithm_name ?? '—'} <code>{focused.algorithm_id ?? ''}</code></dd>
            <dt>数据集</dt><dd>{focused.dataset_name ?? '—'} <code>{focused.dataset_id ?? ''}</code></dd>
            <dt>能力 / 模式</dt><dd>{focused.capability ?? '—'} / {focused.backtest_mode ?? '—'}</dd>
            <dt>创建 / 完成</dt><dd>{fmtTime(focused.created_at)} → {fmtTime(focused.finished_at)}（{fmtDuration(task?.duration_seconds)}）</dd>
            {focused.import_source && <><dt>导入来源</dt><dd><code>{focused.import_source}</code></dd></>}
            {focused.params && <><dt>参数</dt><dd><code className="small-text">{JSON.stringify(focused.params)}</code></dd></>}
          </dl>
          {focused.error && <Alert kind="error">{focused.error}</Alert>}
          {focused.notes && focused.notes.length > 0 && (
            <Alert kind="info"><ul>{focused.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></Alert>
          )}
          {focused.artifacts && focused.artifacts.length > 0 && (
            <>
              <h4>工件</h4>
              <ul className="file-list">
                {focused.artifacts.map((a) => <li key={a.path}><code>{a.name}</code> <span className="muted">{a.path}</span></li>)}
              </ul>
            </>
          )}
          {focused.task_id && (
            <>
              <h4>子进程日志（{task ? `tail 200 行 · 退出码 ${task.returncode ?? '—'}` : '加载中'}）</h4>
              <pre className="logbox">{logs || '（暂无输出）'}</pre>
            </>
          )}
        </Panel>
      )}

      <ImportPanel algos={algos.data ?? []} onDone={refresh} />
    </>
  );
}

// ----------------------------------------------------------------------
// 论文结果 CSV 导入（原 MVP 功能保留：上传 returns / weights / industry / intra）
// ----------------------------------------------------------------------
function ImportPanel({ algos, onDone }: { algos: AlgorithmInfo[]; onDone: () => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    setBusy(true);
    setMsg(null);
    try {
      const fileMap: Record<string, File> = {};
      ['returns', 'weights', 'industry', 'intra'].forEach((k) => {
        const f = fd.get(k);
        if (f instanceof File && f.size > 0) fileMap[k] = f;
      });
      if (!fileMap.returns) throw new Error('必须上传 returns CSV');
      const exp = await api.uploadImport(fileMap, {
        algorithm_id: String(fd.get('algorithm_id') ?? ''),
        name: String(fd.get('name') ?? '') || 'Imported paper result',
        dataset_id: String(fd.get('dataset_id') ?? 'unknown'),
        dataset_name: String(fd.get('dataset_name') ?? 'unknown'),
      });
      setMsg({ kind: 'success', text: `导入成功：${exp.experiment_id}（${exp.name}）` });
      formRef.current?.reset();
      onDone();
    } catch (err) {
      setMsg({ kind: 'error', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="导入论文结果 CSV" subtitle="将两篇论文已导出的回测 CSV 转为统一标准结果（paper_original 口径，费前收益）">
      <form ref={formRef} onSubmit={onSubmit} className="import">
        <p className="param-desc">
          ASACPL：returns + weights（weights 为持仓位置矩阵）；HMMP：returns + industry + intra（行业内条件权重）。
          上传 industry 即按 HMMP 分层口径合成最终权重。
        </p>
        <div className="grid2">
          <div className="form-row">
            <label>所属算法插件</label>
            <select name="algorithm_id" required>
              {algos.map((a) => <option key={a.algorithm_id} value={a.algorithm_id}>{a.name}（{a.algorithm_id}）</option>)}
            </select>
          </div>
          <div className="form-row">
            <label>实验名称</label>
            <input name="name" type="text" placeholder="如 ASACPL 论文表3 复现" />
          </div>
          <div className="form-row">
            <label>数据集 ID</label>
            <input name="dataset_id" type="text" placeholder="asacpl_sp500_test2023" />
          </div>
          <div className="form-row">
            <label>数据集名称</label>
            <input name="dataset_name" type="text" placeholder="S&P500 test2023" />
          </div>
        </div>
        <div className="grid2">
          <div className="form-row">
            <label>returns CSV（必需）</label>
            <input name="returns" type="file" accept=".csv" required />
          </div>
          <div className="form-row">
            <label>weights CSV（ASACPL）</label>
            <input name="weights" type="file" accept=".csv" />
          </div>
          <div className="form-row">
            <label>industry CSV（HMMP）</label>
            <input name="industry" type="file" accept=".csv" />
          </div>
          <div className="form-row">
            <label>intra CSV（HMMP）</label>
            <input name="intra" type="file" accept=".csv" />
          </div>
        </div>
        {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
        <button className="primary" type="submit" disabled={busy}>
          <FileUp size={14} /> {busy ? '上传中…' : '上传并导入'}
        </button>
      </form>
    </Panel>
  );
}
