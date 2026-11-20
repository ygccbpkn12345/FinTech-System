// 主布局：左侧导航 + 顶栏。导航项为固定页面，算法内容一律来自后端注册表
import type { ReactNode } from 'react';
import {
  Activity, BarChart3, Boxes, Database, FlaskConical, LayoutDashboard,
  LineChart, ListFilter, Scale, TrainFront,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';

export interface NavItem {
  hash: string;
  label: string;
  icon: ReactNode;
}

export const NAV_ITEMS: NavItem[] = [
  { hash: '#/', label: '系统概览', icon: <LayoutDashboard size={16} /> },
  { hash: '#/algorithms', label: '算法中心', icon: <Boxes size={16} /> },
  { hash: '#/training', label: '训练中心', icon: <TrainFront size={16} /> },
  { hash: '#/selection', label: '股票筛选', icon: <ListFilter size={16} /> },
  { hash: '#/portfolio', label: '组合配置', icon: <Scale size={16} /> },
  { hash: '#/backtest', label: '回测分析', icon: <LineChart size={16} /> },
  { hash: '#/compare', label: '策略对比', icon: <BarChart3 size={16} /> },
  { hash: '#/datasets', label: '数据集管理', icon: <Database size={16} /> },
  { hash: '#/experiments', label: '实验管理', icon: <FlaskConical size={16} /> },
];

export function MainLayout({ route, children }: { route: string; children: ReactNode }) {
  const health = useApi(() => api.getHealth(), [], 15000);
  const backendOk = !health.loading && !health.error && health.data?.status === 'ok';

  return (
    <div className="app">
      <aside>
        <div className="brand">
          <div className="brand-logo">FP</div>
          <div>
            <div className="brand-name">FinPortfolio</div>
            <div className="brand-sub">算法插件 · 组合分析</div>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map((item) => (
            <a
              key={item.hash}
              href={item.hash}
              className={route === item.hash ? 'active' : ''}
            >
              {item.icon}
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="side-foot">
          <span className={`dot ${backendOk ? 'ok' : 'bad'}`} />
          {backendOk ? '后端已连接' : '后端未连接'}
        </div>
      </aside>
      <div className="main">
        <header>
          <span className="pill">
            <Activity size={13} style={{ marginRight: 4, verticalAlign: -2 }} />
            {NAV_ITEMS.find((n) => n.hash === route)?.label ?? '页面'}
          </span>
          <span className="pill subtle">React + FastAPI 插件化架构</span>
        </header>
        <main>
          {children}
        </main>
      </div>
    </div>
  );
}
