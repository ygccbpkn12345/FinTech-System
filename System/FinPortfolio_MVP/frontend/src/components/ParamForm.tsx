// 动态参数表单：完全由 manifest 参数规范驱动，前端不硬编码任何算法参数
import type { ParameterSpec } from '../types';

export type ParamValues = Record<string, unknown>;

function specDefault(spec: ParameterSpec): unknown {
  if (spec.default !== undefined && spec.default !== null) return spec.default;
  switch (spec.type) {
    case 'int': return 0;
    case 'float': return 0.0;
    case 'bool': return false;
    default: return '';
  }
}

export function defaultParams(specs: ParameterSpec[]): ParamValues {
  const out: ParamValues = {};
  specs.forEach((s) => { out[s.name] = specDefault(s); });
  return out;
}

export function ParamForm({
  specs, values, onChange,
}: {
  specs: ParameterSpec[];
  values: ParamValues;
  onChange: (name: string, value: unknown) => void;
}) {
  if (!specs.length) {
    return <div className="empty">该算法未声明可配置参数</div>;
  }
  return (
    <div className="paramform">
      {specs.map((spec) => {
        const v = values[spec.name];
        const common = {
          id: `param-${spec.name}`,
          'data-testid': `param-${spec.name}`,
        };
        let field;
        if (spec.type === 'bool') {
          field = (
            <select
              {...common}
              value={v === true || v === 'true' ? 'true' : 'false'}
              onChange={(e) => onChange(spec.name, e.target.value === 'true')}
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          );
        } else if (spec.type === 'enum') {
          field = (
            <select
              {...common}
              value={String(v ?? '')}
              onChange={(e) => onChange(spec.name, e.target.value)}
            >
              {(spec.choices ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          );
        } else if (spec.type === 'int' || spec.type === 'float') {
          field = (
            <input
              {...common}
              type="number"
              step={spec.type === 'float' ? 'any' : '1'}
              min={spec.min}
              max={spec.max}
              value={v === undefined || v === null ? '' : String(v)}
              onChange={(e) => onChange(
                spec.name,
                e.target.value === '' ? '' : spec.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value),
              )}
            />
          );
        } else {
          field = (
            <input
              {...common}
              type="text"
              value={v === undefined || v === null ? '' : String(v)}
              onChange={(e) => onChange(spec.name, e.target.value)}
            />
          );
        }
        return (
          <div key={spec.name} className="param-row">
            <label htmlFor={`param-${spec.name}`}>
              {spec.label ?? spec.name}
              <span className="param-type">{spec.type}</span>
            </label>
            {field}
            {spec.description && <div className="param-desc">{spec.description}</div>}
            {(spec.min !== undefined || spec.max !== undefined) && (
              <div className="param-range">
                范围 [{spec.min ?? '−∞'}, {spec.max ?? '+∞'}]
                {spec.default !== undefined && <> · 默认 {String(spec.default)}</>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
