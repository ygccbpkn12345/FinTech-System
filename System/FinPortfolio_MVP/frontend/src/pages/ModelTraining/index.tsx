// 训练中心：选择算法插件（动态）→ 选择能力 → 选择数据集 → manifest 动态参数表单 →
// 提交子进程任务 → 轮询状态与实时日志。前端不硬编码任何算法或参数。
import { useEffect, useMemo, useState } from 'react';
import { Play, Square } from 'lucide-react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { Link, useHashRoute } from '../../router';
import { ParamForm, defaultParams, type ParamValues } from '../../components/ParamForm';
import {
  Alert, EmptyState, ErrorText, Loading, Panel, StatusBadge, fmtDuration,
} from '../../components/ui';
import {
  CAPABILITY_LABELS, RUNNABLE_CAPABILITIES, type AlgorithmInfo,
  type CompatibilityCheck, type DataSplit, type DatasetMeta,
  type ExperimentSummary, type TaskStatus,
} from '../../types';

type SplitFields = { train_start: string; train_end: string; test_start: string; test_end: string };
const EMPTY_SPLIT: SplitFields = { train_start: '', train_end: '', test_start: '', test_end: '' };

export default function ModelTraining() {
  const route = useHashRoute();
  const algos = useApi<AlgorithmInfo[]>(() => api.getAlgorithms(), []);
  const datasets = useApi<DatasetMeta[]>(() => api.getDatasets(), []);

  const runnableAlgos = useMemo(
    () => (algos.data ?? []).filter((a) => a.status === 'READY' && a.capabilities.some((c) => RUNNABLE_CAPABILITIES.includes(c))),
    [algos.data],
  );

  const [algoId, setAlgoId] = useState<string>('');
  const [capability, setCapability] = useState<string>('');
  const [datasetId, setDatasetId] = useState<string>('');
  const [split, setSplit] = useState<SplitFields>(EMPTY_SPLIT);
  const [name, setName] = useState('');
  const [params, setParams] = useState<ParamValues>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [experiment, setExperiment] = useState<ExperimentSummary | null>(null);

  // 深链接：#/training?algorithm=asacpl
  useEffect(() => {
    const q = route.query.get('algorithm');
    if (q && runnableAlgos.some((a) => a.algorithm_id === q)) {
      setAlgoId((prev) => (prev === q ? prev : q));
    }
  }, [route, runnableAlgos]);

  const algo = algoId ? runnableAlgos.find((a) => a.algorithm_id === algoId) : null;
  const runCapabilities = algo ? algo.capabilities.filter((c) => RUNNABLE_CAPABILITIES.includes(c)) : [];

  // 选择算法后：重置能力 / 参数
  useEffect(() => {
    setCapability('');
    setParams({});
  }, [algoId]);

  const config = useApi(
    () => (algoId ? api.getAlgorithmConfig(algoId) : Promise.resolve(null)),
    [algoId],
  );

  // 配置加载后填充默认参数
  useEffect(() => {
    if (config.data) setParams(defaultParams(config.data.parameters));
  }, [config.data]);

  // 数据集选择变化时做兼容性检查；切换数据集时清空已选时间范围
  const [compat, setCompat] = useState<CompatibilityCheck | null>(null);
  useEffect(() => {
    setCompat(null);
    setSplit(EMPTY_SPLIT);
    if (!algoId || !datasetId) return;
    let cancelled = false;
    api.checkCompatibility(datasetId, algoId)
      .then((c) => { if (!cancelled) setCompat(c); })
      .catch(() => { /* 兼容性检查失败不阻塞提交，后端会再校验 */ });
    return () => { cancelled = true; };
  }, [algoId, datasetId]);

  const dataset = datasetId ? (datasets.data ?? []).find((d) => d.dataset_id === datasetId) ?? null : null;

  // 时间范围本地校验（即时反馈；后端会再强校验）
  const splitError = (() => {
    const s = split;
    if (s.train_start && s.train_end && s.train_start > s.train_end) return '训练集起始日不能晚于结束日';
    if (s.test_start && s.test_end && s.test_start > s.test_end) return '测试集起始日不能晚于结束日';
    if (s.train_end && s.test_start && s.train_end >= s.test_start) return '训练集与测试集不得重叠（训练结束日须早于测试起始日）';
    const dr = dataset?.date_range;
    if (dr?.start && dr?.end) {
      const keys = ['train_start', 'train_end', 'test_start', 'test_end'] as const;
      for (const k of keys) {
        const v = s[k];
        if (v && (v < dr.start || v > dr.end)) {
          return `${v} 超出数据集范围 ${dr.start} ~ ${dr.end}`;
        }
      }
    }
    return null;
  })();

  const setSplitField = (k: keyof SplitFields, v: string) =>
    setSplit((prev) => ({ ...prev, [k]: v }));

  const filledSplit = (split: SplitFields): DataSplit | undefined => {
    const out: DataSplit = {};
    (Object.keys(split) as (keyof SplitFields)[]).forEach((k) => {
      if (split[k]) out[k] = split[k];
    });
    return Object.keys(out).length ? out : undefined;
  };

  // 提交后轮询任务状态
  const [task, setTask] = useState<TaskStatus | null>(null);
  const [logs, setLogs] = useState('');
  useEffect(() => {
    if (!experiment?.task_id) return;
    const done = task && ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(task.state);
    if (done) return;
    const timer = setInterval(async () => {
      try {
        const st = await api.getTaskStatus(experiment.task_id!);
        setTask(st);
        const lg = await api.getTaskLogs(experiment.task_id!, 80);
        setLogs(lg.log);
        if (['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(st.state)) {
          const list = await api.getExperiments();
          setExperiment(list.find((e) => e.experiment_id === experiment.experiment_id) ?? experiment);
        }
      } catch { /* 轮询失败静默重试 */ }
    }, 1500);
    return () => clearInterval(timer);
  }, [experiment, task]);

  const onSubmit = async () => {
    setSubmitError(null);
    setTask(null);
    setLogs('');
    setSubmitting(true);
    try {
      const exp = await api.createExperiment({
        algorithm_id: algoId,
        dataset_id: datasetId,
        capability,
        params: params as Record<string, unknown>,
        data_split: filledSplit(split),
        name: name || undefined,
      });
      setExperiment(exp);
      setTask({ state: 'PENDING' } as TaskStatus);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const onCancel = async () => {
    if (!experiment?.task_id) return;
    if (!window.confirm('确认取消该任务？正在运行的子进程将被终止。')) return;
    try { await api.cancelTask(experiment.task_id); } catch (e) { alert(e instanceof Error ? e.message : String(e)); }
  };

  if (algos.loading && !algos.data) return <Loading />;
  if (algos.error) return <ErrorText error={algos.error} />;

  const finished = task && ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(task.state);

  return (
    <>
      <div className="heading">
        <div>
          <h2>训练中心</h2>
          <p className="sub">算法在独立子进程中执行（互不依赖、互不污染），此处仅做调度与日志采集</p>
        </div>
      </div>

      <Panel title="新建任务">
        {runnableAlgos.length === 0 && (
          <EmptyState>注册表中没有可运行的算法插件（需具备 train / predict / backtest / stock_selection 能力）</EmptyState>
        )}
        {runnableAlgos.length > 0 && (
          <div className="train-form">
            <div className="form-row">
              <label>算法插件</label>
              <select value={algoId} onChange={(e) => setAlgoId(e.target.value)} data-testid="select-algorithm">
                <option value="">— 选择算法 —</option>
                {runnableAlgos.map((a) => (
                  <option key={a.algorithm_id} value={a.algorithm_id}>
                    {a.name}（{a.algorithm_id}）
                  </option>
                ))}
              </select>
            </div>

            {algo && (
              <div className="form-row">
                <label>运行能力</label>
                <select value={capability} onChange={(e) => setCapability(e.target.value)} data-testid="select-capability">
                  <option value="">— 选择能力 —</option>
                  {runCapabilities.map((c) => (
                    <option key={c} value={c}>{CAPABILITY_LABELS[c] ?? c}</option>
                  ))}
                </select>
                {algo.warnings.length > 0 && (
                  <div className="param-desc warn-text">⚠ {algo.warnings.join('；')}</div>
                )}
              </div>
            )}

            <div className="form-row">
              <label>数据集</label>
              <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)} data-testid="select-dataset">
                <option value="">— 选择数据集 —</option>
                {(datasets.data ?? []).map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>
                    {d.name}（{d.dataset_id} · {d.market} · {d.date_range.days} 天）
                  </option>
                ))}
              </select>
              {(datasets.data ?? []).length === 0 && (
                <div className="param-desc">尚无注册数据集，请先在数据集管理页登记</div>
              )}
            </div>

            {datasetId && dataset && (
              <div className="form-row">
                <label>数据时间范围（可选）</label>
                <div className="split-grid">
                  <div className="split-pair">
                    <span className="split-label">训练集</span>
                    <input
                      type="date"
                      value={split.train_start}
                      min={dataset.date_range.start ?? undefined}
                      max={dataset.date_range.end ?? undefined}
                      onChange={(e) => setSplitField('train_start', e.target.value)}
                      data-testid="split-train-start"
                    />
                    <span className="split-sep">~</span>
                    <input
                      type="date"
                      value={split.train_end}
                      min={dataset.date_range.start ?? undefined}
                      max={dataset.date_range.end ?? undefined}
                      onChange={(e) => setSplitField('train_end', e.target.value)}
                      data-testid="split-train-end"
                    />
                  </div>
                  <div className="split-pair">
                    <span className="split-label">测试集</span>
                    <input
                      type="date"
                      value={split.test_start}
                      min={dataset.date_range.start ?? undefined}
                      max={dataset.date_range.end ?? undefined}
                      onChange={(e) => setSplitField('test_start', e.target.value)}
                      data-testid="split-test-start"
                    />
                    <span className="split-sep">~</span>
                    <input
                      type="date"
                      value={split.test_end}
                      min={dataset.date_range.start ?? undefined}
                      max={dataset.date_range.end ?? undefined}
                      onChange={(e) => setSplitField('test_end', e.target.value)}
                      data-testid="split-test-end"
                    />
                  </div>
                </div>
                <div className="param-desc">
                  数据集范围：{dataset.date_range.start ?? '未知'} ~ {dataset.date_range.end ?? '未知'}
                  （{dataset.date_range.days} 个交易日）· 留空任一侧 = 不限制；全部留空 = 使用全量
                  <button type="button" className="btn-link" onClick={() => setSplit(EMPTY_SPLIT)}>重置为全量</button>
                </div>
                {splitError && <div className="param-desc warn-text" data-testid="split-error">⚠ {splitError}</div>}
              </div>
            )}

            {compat && (
              compat.compatible
                ? <Alert kind="success">兼容性检查通过{compat.matched_modalities ? `（匹配模态：${compat.matched_modalities.join(' + ')}）` : ''}</Alert>
                : <Alert kind="warn">兼容性警告：{compat.warnings.join('；') || '不兼容'}。仍可提交，后端与插件会再次校验。</Alert>
            )}

            {algoId && config.loading && <Loading label="加载算法参数定义…" />}
            {algoId && config.error && <ErrorText error={config.error} />}
            {config.data && config.data.parameters.length > 0 && (
              <>
                <h4 className="form-section">运行参数（来自插件 manifest，动态生成）</h4>
                <ParamForm
                  specs={config.data.parameters}
                  values={params}
                  onChange={(n, v) => setParams((prev) => ({ ...prev, [n]: v }))}
                />
              </>
            )}

            <div className="form-row">
              <label>实验名称（可选）</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="留空自动生成" />
            </div>

            {submitError && <Alert kind="error">提交失败：{submitError}</Alert>}

            <div className="form-actions">
              <button
                className="primary"
                disabled={!algoId || !capability || !datasetId || !!splitError || submitting}
                onClick={onSubmit}
                data-testid="submit-experiment"
              >
                <Play size={14} /> {submitting ? '提交中…' : '提交任务'}
              </button>
              {experiment?.task_id && !finished && (
                <button className="outline danger" onClick={onCancel}><Square size={13} /> 取消任务</button>
              )}
            </div>
          </div>
        )}
      </Panel>

      {experiment && (
        <Panel
          title={`任务 · ${experiment.name}`}
          subtitle={<code>{experiment.experiment_id}</code>}
          actions={task && <StatusBadge status={task.state} />}
        >
          {task && (
            <div className="cards">
              <div className="metric"><div className="m-label">状态</div><div className="m-value"><StatusBadge status={task.state} /></div></div>
              <div className="metric"><div className="m-label">已运行</div><div className="m-value">{fmtDuration(task.duration_seconds)}</div></div>
              <div className="metric"><div className="m-label">退出码</div><div className="m-value">{task.returncode ?? '—'}</div></div>
              <div className="metric"><div className="m-label">超时上限</div><div className="m-value">{task.timeout_seconds}s</div></div>
            </div>
          )}
          {experiment.error && <Alert kind="error">{experiment.error}</Alert>}
          {finished && task?.state === 'SUCCEEDED' && (
            <Alert kind="success">
              任务完成。
              <Link className="btn-link" to={`/backtest?experiment=${experiment.experiment_id}`}>查看回测结果 →</Link>
              <Link className="btn-link" to={`/portfolio?experiment=${experiment.experiment_id}`}>查看组合权重 →</Link>
            </Alert>
          )}
          <h4>子进程日志（实时）</h4>
          <pre className="logbox">{logs || '（等待输出…）'}</pre>
        </Panel>
      )}
    </>
  );
}
