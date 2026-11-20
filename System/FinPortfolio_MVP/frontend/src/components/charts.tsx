// 图表组件：基于 recharts 的净值/回撤/权重/对比曲线封装
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

const GRID = '#d8e2f1';
const AXIS = { fill: '#5b6b85', fontSize: 11 };
const TOOLTIP_STYLE = {
  contentStyle: {
    background: '#0f1c33', border: '1px solid #2869cf', borderRadius: 8,
    color: '#e8eefc', fontSize: 12,
  },
  labelStyle: { color: '#9fb4d8' },
};

const PALETTE = [
  '#2869cf', '#18a058', '#d0342c', '#e6a23c', '#7a5af8',
  '#0aa2c0', '#e675a8', '#8d6e63', '#5b8def', '#67c23a',
  '#f56c6c', '#b88230', '#6f42c1', '#20b2aa', '#cd5c5c',
  '#4169e1', '#32cd32', '#ffa07a', '#ba55d3', '#4682b4',
];

export function WealthChart({
  dates, values, netValues, height = 300,
}: {
  dates: string[];
  values: number[];
  netValues?: number[];
  height?: number;
}) {
  const data = dates.map((d, i) => ({
    date: d,
    gross: values[i],
    ...(netValues ? { net: netValues[i] } : {}),
  }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="gWealth" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2869cf" stopOpacity={0.28} />
            <stop offset="100%" stopColor="#2869cf" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} minTickGap={48} />
        <YAxis tick={AXIS} domain={['auto', 'auto']} tickFormatter={(v: number) => v.toFixed(2)} />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number | string) => (typeof v === 'number' ? v.toFixed(4) : v)} />
        <Area type="monotone" dataKey="gross" name="净值（毛）" stroke="#2869cf" strokeWidth={2} fill="url(#gWealth)" />
        {netValues && (
          <Area type="monotone" dataKey="net" name="净值（扣费）" stroke="#18a058" strokeWidth={1.6} fill="none" fillOpacity={0} strokeDasharray="5 3" />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function DrawdownChart({
  dates, drawdown, height = 180,
}: {
  dates: string[];
  drawdown: number[];
  height?: number;
}) {
  const data = dates.map((d, i) => ({ date: d, dd: drawdown[i] }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} minTickGap={48} />
        <YAxis tick={AXIS} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number | string) => (typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : v)} />
        <Area type="monotone" dataKey="dd" name="回撤" stroke="#d0342c" strokeWidth={1.6} fill="#d0342c" fillOpacity={0.12} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function WeightsStackedChart({
  dates, weights, cashWeights, height = 320, maxCodes = 20,
}: {
  dates: string[];
  weights: Record<string, number>[];
  cashWeights: number[];
  height?: number;
  maxCodes?: number;
}) {
  const codes = Array.from(new Set(weights.flatMap((w) => Object.keys(w)))).sort();
  const shown = codes.slice(0, maxCodes);
  const hidden = codes.length - shown.length;
  const data = dates.map((d, i) => {
    const row: Record<string, string | number> = { date: d };
    shown.forEach((c) => { row[c] = weights[i][c] ?? 0; });
    if (cashWeights.length) row['现金'] = cashWeights[i] ?? 0;
    return row;
  });
  const series = [...shown, ...(cashWeights.length ? ['现金'] : [])];
  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" tick={AXIS} minTickGap={48} />
          <YAxis tick={AXIS} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
          <Tooltip {...TOOLTIP_STYLE} formatter={(v: number | string) => (typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : v)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((code, idx) => (
            <Area
              key={code}
              type="monotone"
              dataKey={code}
              stackId="w"
              stroke={code === '现金' ? '#8d99ae' : PALETTE[idx % PALETTE.length]}
              fill={code === '现金' ? '#8d99ae' : PALETTE[idx % PALETTE.length]}
              fillOpacity={0.85}
              strokeWidth={0.6}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      {hidden > 0 && (
        <div className="chart-note">股票数量较多，图中仅展示前 {maxCodes} 只（共 {codes.length} 只，其余归并省略）</div>
      )}
    </div>
  );
}

export function CompareChart({
  series, height = 340,
}: {
  series: { name: string; dates: string[]; values: number[] }[];
  height?: number;
}) {
  // 对齐到最长日期序列；缺失日期置 null 由 recharts 断开
  const allDates: string[] = [];
  series.forEach((s) => s.dates.forEach((d) => {
    if (!allDates.includes(d)) allDates.push(d);
  }));
  allDates.sort();
  const data = allDates.map((d) => {
    const row: Record<string, string | number | null> = { date: d };
    series.forEach((s) => {
      const i = s.dates.indexOf(d);
      row[s.name] = i >= 0 ? s.values[i] : null;
    });
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} minTickGap={48} />
        <YAxis tick={AXIS} domain={['auto', 'auto']} tickFormatter={(v: number) => v.toFixed(2)} />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number | string) => (typeof v === 'number' ? v.toFixed(4) : v)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {series.map((s, idx) => (
          <Line
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stroke={PALETTE[idx % PALETTE.length]}
            strokeWidth={1.8}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function TurnoverChart({
  dates, turnover, height = 180,
}: {
  dates: string[];
  turnover: number[];
  height?: number;
}) {
  const data = dates.map((d, i) => ({ date: d, t: turnover[i] }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} minTickGap={48} />
        <YAxis tick={AXIS} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number | string) => (typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : v)} />
        <Bar dataKey="t" name="单边换手率" fill="#e6a23c" />
      </BarChart>
    </ResponsiveContainer>
  );
}
