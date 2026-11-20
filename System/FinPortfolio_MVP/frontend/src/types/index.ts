// 与后端 API 对应的类型定义（仅描述接口形状，不引入算法硬编码）

export interface PaperInfo {
  title: string;
  authors?: string[];
  venue?: string;
  year?: number;
  url?: string;
  note?: string;
}

export interface ParameterSpec {
  name: string;
  label?: string;
  type: 'int' | 'float' | 'str' | 'bool' | 'enum';
  default: unknown;
  min?: number;
  max?: number;
  choices?: string[];
  description?: string;
  advanced?: boolean;
  required?: boolean;
}

export interface DatasetRequirement {
  markets: string[];
  modalities: string[];
  required_fields?: string[];
  description?: string;
}

export interface AlgorithmInfo {
  algorithm_id: string;
  name: string;
  version: string | null;
  description: string;
  framework: string | null;
  paper: PaperInfo;
  capabilities: string[];
  dataset_requirements: DatasetRequirement[];
  status: 'READY' | 'ERROR';
  error?: string | null;
  warnings: string[];
  plugin_dir: string;
  python_executable?: string | null;
  parameters?: ParameterSpec[];
  outputs?: { result_format: string; artifacts?: string[] };
  execution?: {
    adapter_file: string;
    original_code_dir: string | null;
    default_timeout_seconds: number;
    max_timeout_seconds: number;
  };
}

export interface AlgorithmConfig {
  algorithm_id: string;
  parameters: ParameterSpec[];
  capabilities: string[];
  default_params: Record<string, unknown>;
  warnings: string[];
}

export interface DatasetMeta {
  dataset_id: string;
  name: string;
  market: string;
  assets: string[];
  date_range: { start: string | null; end: string | null; days: number };
  frequency: string;
  feature_schema: string[];
  available_modalities: string[];
  storage_mode: string;
  storage_path: string;
  files: Record<string, string>;
  version: string;
  description: string;
  provenance: string;
}

export interface DatasetValidateReport {
  dataset_id: string;
  valid: boolean;
  problems: string[];
  file_reports: Record<string, {
    path: string;
    exists: boolean;
    columns?: string[];
    date_range?: { start: string | null; end: string | null; unique_days: number; invalid_dates: number };
    error?: string;
  }>;
}

export interface CompatibilityCheck {
  algorithm_id: string;
  dataset_id: string;
  compatible: boolean;
  matched_modalities: string[] | null;
  warnings: string[];
}

export interface DataSplit {
  train_start?: string;
  train_end?: string;
  test_start?: string;
  test_end?: string;
}

export interface ExperimentSummary {
  experiment_id: string;
  name: string;
  kind: 'run' | 'import';
  algorithm_id: string | null;
  algorithm_name: string | null;
  algorithm_version: string | null;
  dataset_id: string | null;
  dataset_name: string | null;
  capability: string | null;
  backtest_mode: string | null;
  status: string;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  result_summary: Record<string, number | null> | null;
  task_id: string | null;
  data_split?: DataSplit | null;
  params?: Record<string, unknown>;
  notes?: string[];
  artifacts?: { name: string; path: string; kind: string; description?: string }[];
  import_source?: string;
}

export interface TaskStatus {
  task_id: string;
  state: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
  command: string[];
  cwd: string;
  timeout_seconds: number;
  returncode: number | null;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  duration_seconds: number;
}

export interface TaskLogs {
  task_id: string;
  state: string;
  log: string;
}

export interface MetricAssumptions {
  trading_days_per_year: number;
  risk_free_rate: number;
  annualization: string;
  return_type: string;
}

export interface ArtifactInfo {
  name: string;
  path: string;
  kind: string;
  description?: string;
}

export interface PortfolioResult {
  schema_version: string;
  experiment_id: string;
  algorithm_id: string;
  algorithm_version: string;
  dataset_id: string;
  dataset_version: string;
  configuration: Record<string, unknown>;
  backtest_mode: 'paper_original' | 'unified_rebalance';
  trading_protocol: Record<string, unknown>;
  dates: string[];
  daily_returns: number[];
  net_daily_returns?: number[];
  cost_included: boolean;
  portfolio_values: number[];
  stock_weights: Record<string, number>[];
  cash_weights: number[];
  industry_weights?: Record<string, number>[];
  turnover?: number[];
  metrics: Record<string, number | null>;
  metric_assumptions: MetricAssumptions;
  artifacts: ArtifactInfo[];
  stock_selection?: { date: string; ranked: { code: string; score?: number; rank?: number }[]; top_k: string[] }[];
  execution_status: string;
  notes: string[];
  asset_label_mode: 'ticker' | 'position_index';
  weights_available: boolean;
}

export interface CurveData {
  experiment_id: string;
  dates: string[];
  values: number[];
  daily_returns: number[];
  drawdown: number[];
  net_daily_returns?: number[];
}

export interface SystemOverview {
  algorithms_registered: number;
  algorithms_failed: number;
  datasets: number;
  experiments_total: number;
  experiments_succeeded: number;
  experiments_failed: number;
  running_tasks: { experiment_id: string; name: string; algorithm_id: string; status: string }[];
  recent_experiments: ExperimentSummary[];
  latest_portfolio_curve: {
    experiment_id: string;
    name: string;
    dates: string[];
    values: number[];
    drawdown: number[];
    metrics: Record<string, number | null>;
  } | null;
  plugin_scan: { plugins_dir: string; registered: string[]; failed: Record<string, string>; total_scanned: number };
}

export interface CompareResponse {
  fair: boolean;
  warnings: string[];
  experiments: {
    experiment_id: string;
    name: string;
    algorithm_id: string;
    algorithm_name: string;
    dataset_id: string;
    backtest_mode: string;
    dates: string[];
    portfolio_values: number[];
    metrics: Record<string, number | null>;
    metric_assumptions: MetricAssumptions;
  }[];
}

export const RUNNABLE_CAPABILITIES = ['train', 'predict', 'backtest', 'stock_selection'];

export const CAPABILITY_LABELS: Record<string, string> = {
  train: '模型训练',
  predict: '推理预测',
  backtest: '回测',
  stock_selection: '股票筛选',
  industry_allocation: '行业配置',
  news_analysis: '新闻分析',
  portfolio_weights: '组合权重',
  import: '结果导入',
};

export const STATE_LABELS: Record<string, string> = {
  PENDING: '排队中',
  RUNNING: '运行中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};
