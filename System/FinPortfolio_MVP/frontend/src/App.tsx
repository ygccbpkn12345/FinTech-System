// 根组件：hash 路由分发到 9 个页面
import { Suspense, lazy, type LazyExoticComponent } from 'react';
import { useHashRoute } from './router';
import { MainLayout } from './layouts/MainLayout';
import { Loading } from './components/ui';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const AlgorithmRegistry = lazy(() => import('./pages/AlgorithmRegistry'));
const ModelTraining = lazy(() => import('./pages/ModelTraining'));
const StockSelection = lazy(() => import('./pages/StockSelection'));
const PortfolioAnalysis = lazy(() => import('./pages/PortfolioAnalysis'));
const Backtest = lazy(() => import('./pages/Backtest'));
const StrategyComparison = lazy(() => import('./pages/StrategyComparison'));
const DatasetManager = lazy(() => import('./pages/DatasetManager'));
const ExperimentManager = lazy(() => import('./pages/ExperimentManager'));

type PageComponent = LazyExoticComponent<() => JSX.Element>;

const ROUTES: Record<string, PageComponent> = {
  '/': Dashboard,
  '/algorithms': AlgorithmRegistry,
  '/training': ModelTraining,
  '/selection': StockSelection,
  '/portfolio': PortfolioAnalysis,
  '/backtest': Backtest,
  '/compare': StrategyComparison,
  '/datasets': DatasetManager,
  '/experiments': ExperimentManager,
};

export default function App() {
  const route = useHashRoute();
  const Page = ROUTES[route.path] ?? NotFound;
  return (
    <MainLayout route={route.hash}>
      <Suspense fallback={<Loading />}>
        <Page />
      </Suspense>
    </MainLayout>
  );
}

function NotFound() {
  return (
    <div className="empty">
      页面不存在：<code>{window.location.hash}</code>
      <p className="param-desc">
        <a href="#/">返回系统概览</a>
      </p>
    </div>
  );
}
