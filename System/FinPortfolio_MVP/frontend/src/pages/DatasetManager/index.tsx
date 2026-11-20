// 数据集管理：元信息浏览、完整性校验、与算法插件的兼容性检查
import { useState } from 'react';
import { RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { api } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import {
  Alert, DataTable, EmptyState, ErrorText, Loading, Panel,
} from '../../components/ui';
import type { DatasetMeta, DatasetValidateReport, CompatibilityCheck } from '../../types';

export default function DatasetManager() {
  const { data, loading, error, refresh } = useApi<DatasetMeta[]>(() => api.getDatasets(), []);
  const algos = useApi(() => api.getAlgorithms(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<DatasetValidateReport | null>(null);
  const [compat, setCompat] = useState<Record<string, CompatibilityCheck>>({});
  const [busy, setBusy] = useState(false);

  const detail = selected ? (data ?? []).find((d) => d.dataset_id === selected) : null;

  const onValidate = async (id: string) => {
    setBusy(true);
    try { setReport(await api.validateDataset(id)); } catch (e) { setReport(null); alert(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const onCheckCompat = async (datasetId: string, algorithmId: string) => {
    setBusy(true);
    try {
      const c = await api.checkCompatibility(datasetId, algorithmId);
      setCompat((prev) => ({ ...prev, [algorithmId]: c }));
    } finally { setBusy(false); }
  };

  const onDelete = async (id: string) => {
    if (!window.confirm(`确认删除数据集 ${id}？该操作不删除原始数据文件，仅移除注册信息。`)) return;
    try {
      await api.deleteDataset(id);
      if (selected === id) { setSelected(null); setReport(null); }
      refresh();
    } catch (e) { alert(e instanceof Error ? e.message : String(e)); }
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorText error={error} />;

  const datasets = data ?? [];

  return (
    <>
      <div className="heading">
        <div>
          <h2>数据集管理</h2>
          <p className="sub">注册数据集的元信息、完整性与算法兼容性（原始数据保持原格式，平台不强行统一）</p>
        </div>
        <button className="outline" onClick={refresh}><RefreshCw size={14} /> 刷新</button>
      </div>

      <Panel title="已注册数据集">
        <DataTable
          columns={[
            { key: 'id', header: 'ID', render: (d) => <code>{d.dataset_id}</code> },
            { key: 'name', header: '名称', render: (d) => d.name },
            { key: 'market', header: '市场', render: (d) => d.market },
            { key: 'assets', header: '标的数', render: (d) => d.assets.length },
            { key: 'days', header: '交易日数', render: (d) => d.date_range.days },
            { key: 'range', header: '时间范围', render: (d) => d.date_range.start ? `${d.date_range.start} ~ ${d.date_range.end}` : '—' },
            { key: 'modalities', header: '可用模态', render: (d) => d.available_modalities.join(' + ') },
            {
              key: 'ops', header: '操作', render: (d) => (
                <div className="row-ops">
                  <button className="outline small" onClick={() => { setSelected(d.dataset_id); setReport(null); setCompat({}); }}>详情</button>
                  <button className="outline small" disabled={busy} onClick={() => onValidate(d.dataset_id)}>校验</button>
                  <button className="outline small danger" onClick={() => onDelete(d.dataset_id)}><Trash2 size={12} /> 删除</button>
                </div>
              ),
            },
          ]}
          rows={datasets}
          empty="尚未注册数据集。请运行 scripts/register_datasets.py 或通过 API 登记"
        />
      </Panel>

      {detail && (
        <Panel title={`数据集详情 · ${detail.dataset_id}`} subtitle={detail.name}>
          <div className="grid2">
            <div>
              <dl className="kv">
                <dt>市场</dt><dd>{detail.market}</dd>
                <dt>频率</dt><dd>{detail.frequency}</dd>
                <dt>标的数</dt><dd>{detail.assets.length}</dd>
                <dt>交易日数</dt><dd>{detail.date_range.days}（{detail.date_range.start} ~ {detail.date_range.end}）</dd>
                <dt>存储模式</dt><dd>{detail.storage_mode}</dd>
                <dt>版本</dt><dd>{detail.version}</dd>
                <dt>来源</dt><dd>{detail.provenance}</dd>
                <dt>描述</dt><dd>{detail.description}</dd>
              </dl>
              <h4>文件清单</h4>
              <ul className="file-list">
                {Object.entries(detail.files).map(([name, path]) => (
                  <li key={name}><code>{name}</code> → {path}</li>
                ))}
              </ul>
            </div>
            <div>
              <h4>特征字段</h4>
              <div className="tag-cloud">
                {detail.feature_schema.map((f) => <span key={f} className="pill subtle">{f}</span>)}
              </div>
              <h4>标的列表{detail.assets.length > 30 ? `（前 30 / ${detail.assets.length}）` : ''}</h4>
              <div className="tag-cloud">
                {detail.assets.slice(0, 30).map((a) => <span key={a} className="pill subtle">{a}</span>)}
              </div>
            </div>
          </div>
        </Panel>
      )}

      {report && (
        <Panel
          title="完整性校验报告"
          actions={<span className={`pill ${report.valid ? 'badge-ok' : 'badge-err'}`}>
            <ShieldCheck size={12} style={{ verticalAlign: -1, marginRight: 3 }} />
            {report.valid ? '通过' : '存在问题'}
          </span>}
        >
          {!report.valid && report.problems.length > 0 && (
            <Alert kind="error"><ul>{report.problems.map((p, i) => <li key={i}>{p}</li>)}</ul></Alert>
          )}
          <DataTable
            columns={[
              { key: 'file', header: '文件', render: (r) => <code>{r.name}</code> },
              { key: 'exists', header: '存在', render: (r) => (r.report.exists ? '✓' : '✗') },
              {
                key: 'cols', header: '列', render: (r) => r.report.columns
                  ? <span className="mono small-text">{r.report.columns.join(', ')}</span> : '—',
              },
              {
                key: 'range', header: '日期范围', render: (r) => r.report.date_range
                  ? `${r.report.date_range.start ?? '?'} ~ ${r.report.date_range.end ?? '?'}（${r.report.date_range.unique_days} 天，异常 ${r.report.date_range.invalid_dates} 行）` : '—',
              },
              { key: 'err', header: '错误', render: (r) => r.report.error ?? '—' },
            ]}
            rows={Object.entries(report.file_reports).map(([name, rep]) => ({ name, report: rep }))}
          />
        </Panel>
      )}

      {detail && (
        <Panel title="算法兼容性检查" subtitle={`针对数据集 ${detail.dataset_id}`}>
          <div className="compat-list">
            {(algos.data ?? []).map((a) => {
              const c = compat[a.algorithm_id];
              return (
                <div key={a.algorithm_id} className="compat-row">
                  <div>
                    <strong>{a.name}</strong> <code className="small-text">{a.algorithm_id}</code>
                  </div>
                  <button className="outline small" disabled={busy} onClick={() => onCheckCompat(detail.dataset_id, a.algorithm_id)}>
                    检查
                  </button>
                  {c && (
                    <div className={`compat-result ${c.compatible ? 'ok' : 'bad'}`}>
                      {c.compatible ? '✓ 兼容' : '✗ 不兼容'}
                      {c.matched_modalities && <span className="muted">（匹配模态：{c.matched_modalities.join(' + ') || '无'}）</span>}
                      {c.warnings.length > 0 && (
                        <ul>{c.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Panel>
      )}
    </>
  );
}
