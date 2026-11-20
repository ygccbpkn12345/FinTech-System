// 通用 UI 组件：面板、指标卡、状态徽章、数据表、空态、提示
import type { ReactNode } from 'react';
import { STATE_LABELS } from '../types';

export function Panel({
  title, subtitle, actions, children, className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className ?? ''}`}>
      {(title || actions) && (
        <div className="panel-head">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <div className="panel-sub">{subtitle}</div>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function MetricCard({
  label, value, hint, tone,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'positive' | 'negative';
}) {
  const cls = tone === 'positive' ? 'pos' : tone === 'negative' ? 'neg' : '';
  return (
    <div className="metric">
      <div className="m-label">{label}</div>
      <div className={`m-value ${cls}`}>{value}</div>
      {hint && <div className="m-hint">{hint}</div>}
    </div>
  );
}

const STATE_TONE: Record<string, string> = {
  SUCCEEDED: 'ok',
  RUNNING: 'run',
  PENDING: 'pend',
  FAILED: 'err',
  CANCELLED: 'mut',
  READY: 'ok',
  ERROR: 'err',
};

export function StatusBadge({ status }: { status: string }) {
  const tone = STATE_TONE[status] ?? 'mut';
  return <span className={`pill badge-${tone}`}>{STATE_LABELS[status] ?? status}</span>;
}

export function CapabilityBadge({ cap, label }: { cap: string; label: string }) {
  return <span className={`pill cap-${cap}`} title={cap}>{label}</span>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Alert({
  kind = 'info', children,
}: {
  kind?: 'info' | 'warn' | 'error' | 'success';
  children: ReactNode;
}) {
  return <div className={`alert alert-${kind}`}>{children}</div>;
}

export function Loading({ label = '加载中…' }: { label?: string }) {
  return <div className="loading">{label}</div>;
}

export function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="error">请求失败：{error}</div>;
}

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  width?: string;
}

export function DataTable<T>({ columns, rows, empty }: {
  columns: Column<T>[];
  rows: T[];
  empty?: ReactNode;
}) {
  if (!rows.length) return <EmptyState>{empty ?? '暂无数据'}</EmptyState>;
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={c.width ? { width: c.width } : undefined}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key}>{c.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(digits);
}

export function fmtTime(ts: number | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return '—';
  if (sec < 60) return `${sec.toFixed(0)} 秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分 ${Math.round(sec % 60)} 秒`;
  return `${Math.floor(sec / 3600)} 时 ${Math.round((sec % 3600) / 60)} 分`;
}
