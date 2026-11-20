// 算法中心：从 /api/algorithms 动态渲染注册表内容，前端不硬编码任何算法
import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import { Link } from '../../router';
import {
  Alert, CapabilityBadge, DataTable, EmptyState, ErrorText, Loading, Panel, StatusBadge,
} from '../../components/ui';
import { CAPABILITY_LABELS, type AlgorithmInfo } from '../../types';

export default function AlgorithmRegistry() {
  const { data, loading, error, refresh } = useApi<AlgorithmInfo[]>(() => api.getAlgorithms(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);

  // 详情（含 parameters / execution）单独请求：列表接口不带重型字段
  const detailQuery = useApi<AlgorithmInfo | null>(
    () => (selected ? api.getAlgorithm(selected) : Promise.resolve(null)),
    [selected],
  );
  const detail = detailQuery.data;

  const onReloadRegistry = async () => {
    setReloading(true);
    setReloadMsg(null);
    try {
      const r = await api.reloadRegistry();
      setReloadMsg(`重新扫描完成：注册 ${r.registered.length} 个，失败 ${Object.keys(r.failed).length} 个`);
      refresh();
    } catch (e) {
      setReloadMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setReloading(false);
    }
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorText error={error} />;

  const algos = data ?? [];

  return (
    <>
      <div className="heading">
        <div>
          <h2>算法中心</h2>
          <p className="sub">已注册算法均以插件形式接入：{algos.length} 个</p>
        </div>
        <button className="outline" onClick={onReloadRegistry} disabled={reloading}>
          <RefreshCw size={14} /> {reloading ? '扫描中…' : '重新扫描插件'}
        </button>
      </div>

      {reloadMsg && <Alert kind="info">{reloadMsg}</Alert>}

      {algos.length === 0 && (
        <Panel>
          <EmptyState>
            注册表为空。请将插件目录放入后端 plugins/ 后点击「重新扫描插件」，
            或检查后端 FINPORTFOLIO_PLUGINS_DIR 环境变量。
          </EmptyState>
        </Panel>
      )}

      <div className="cards algo-cards">
        {algos.map((a) => (
          <button
            key={a.algorithm_id}
            className={`panel algo-card ${selected === a.algorithm_id ? 'selected' : ''}`}
            onClick={() => setSelected(selected === a.algorithm_id ? null : a.algorithm_id)}
          >
            <div className="algo-card-head">
              <strong>{a.name}</strong>
              <StatusBadge status={a.status} />
            </div>
            <code className="algo-id">{a.algorithm_id}{a.version ? `@${a.version}` : ''}</code>
            <p className="algo-desc">{a.description}</p>
            <div className="algo-caps">
              {a.capabilities.map((c) => (
                <CapabilityBadge key={c} cap={c} label={CAPABILITY_LABELS[c] ?? c} />
              ))}
            </div>
            <div className="algo-meta">
              <span>{a.framework ?? '未知框架'}</span>
              {a.paper?.year && <span>· {a.paper.year}</span>}
            </div>
          </button>
        ))}
      </div>

      {algos.some((a) => a.status === 'ERROR') && (
        <Panel title="加载失败的插件">
          <Alert kind="error">
            以下插件 manifest 校验未通过，已被注册表隔离（不影响其他算法运行）：
            <ul>
              {algos.filter((a) => a.status === 'ERROR').map((a) => (
                <li key={a.algorithm_id}><code>{a.algorithm_id}</code>：{a.error}</li>
              ))}
            </ul>
          </Alert>
        </Panel>
      )}

      {detail && (
        <Panel
          title={`${detail.name} · 插件详情`}
          subtitle={<code>{detail.plugin_dir}</code>}
          actions={<Link className="btn-link" to={`/training?algorithm=${detail.algorithm_id}`}>去训练中心运行 →</Link>}
        >
          {detail.error && <Alert kind="error">加载错误：{detail.error}</Alert>}
          {detail.warnings.length > 0 && (
            <Alert kind="warn">
              <ul>{detail.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </Alert>
          )}

          <div className="grid2">
            <div>
              <h4>论文信息</h4>
              <dl className="kv">
                <dt>标题</dt><dd>{detail.paper?.title ?? '—'}</dd>
                {detail.paper?.authors?.length ? <><dt>作者</dt><dd>{detail.paper.authors.join(', ')}</dd></> : null}
                {detail.paper?.venue ? <><dt>发表</dt><dd>{detail.paper.venue}{detail.paper.year ? ` (${detail.paper.year})` : ''}</dd></> : null}
                {detail.paper?.url ? <><dt>链接</dt><dd><a href={detail.paper.url} target="_blank" rel="noreferrer">{detail.paper.url}</a></dd></> : null}
                {detail.paper?.note ? <><dt>备注</dt><dd>{detail.paper.note}</dd></> : null}
              </dl>

              <h4>运行环境</h4>
              <dl className="kv">
                <dt>Python 解释器</dt><dd><code>{detail.python_executable ?? '后端默认'}</code></dd>
                {detail.execution && <>
                  <dt>适配器</dt><dd><code>{detail.execution.adapter_file}</code></dd>
                  <dt>原始代码目录</dt><dd>{detail.execution.original_code_dir ?? '—'}</dd>
                  <dt>默认超时</dt><dd>{detail.execution.default_timeout_seconds} 秒（上限 {detail.execution.max_timeout_seconds} 秒）</dd>
                </>}
              </dl>
            </div>

            <div>
              <h4>能力</h4>
              <div className="algo-caps">
                {detail.capabilities.map((c) => (
                  <CapabilityBadge key={c} cap={c} label={CAPABILITY_LABELS[c] ?? c} />
                ))}
              </div>

              <h4>数据集要求</h4>
              {(detail.dataset_requirements ?? []).map((req, i) => (
                <div key={i} className="req-block">
                  <div>市场：{req.markets.join(' / ')}</div>
                  <div>模态：{req.modalities.join(' + ')}</div>
                  {req.required_fields?.length ? <div>必需字段：{req.required_fields.join(', ')}</div> : null}
                  {req.description ? <div className="muted">{req.description}</div> : null}
                </div>
              ))}

              <h4>参数（manifest 声明）</h4>
              <DataTable
                columns={[
                  { key: 'name', header: '参数', render: (p) => <code>{p.name}</code> },
                  { key: 'type', header: '类型', render: (p) => p.type },
                  { key: 'default', header: '默认值', render: (p) => String(p.default) },
                  {
                    key: 'range', header: '范围/选项', render: (p) =>
                      p.choices ? p.choices.join(' | ') :
                      (p.min !== undefined || p.max !== undefined) ? `[${p.min ?? '−∞'}, ${p.max ?? '+∞'}]` : '—',
                  },
                ]}
                rows={detail.parameters ?? []}
                empty="未声明参数"
              />
              <Link className="btn-link" to={`/training?algorithm=${detail.algorithm_id}`}>在训练中心动态生成参数表单 →</Link>
            </div>
          </div>
        </Panel>
      )}
    </>
  );
}
