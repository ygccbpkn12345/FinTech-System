// 统一 API 客户端：所有请求经由 Vite 代理或直连后端，禁止在前端硬编码算法信息

const BASE = import.meta.env.VITE_API_BASE ?? '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data && typeof data.detail === 'string') detail = data.detail;
      else if (data && typeof data.detail === 'object') detail = JSON.stringify(data.detail);
    } catch {
      /* 保留默认错误信息 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // 系统
  getOverview: () => request<import('../types').SystemOverview>('/api/system/overview'),
  getHealth: () => request<{ status: string }>('/api/system/health'),

  // 算法
  getAlgorithms: () => request<import('../types').AlgorithmInfo[]>('/api/algorithms'),
  getAlgorithm: (id: string) => request<import('../types').AlgorithmInfo>(`/api/algorithms/${id}`),
  getAlgorithmConfig: (id: string) =>
    request<import('../types').AlgorithmConfig>(`/api/algorithms/${id}/config`),
  reloadRegistry: () =>
    request<{ registered: string[]; failed: Record<string, string> }>('/api/algorithms/registry/reload'),

  // 数据集
  getDatasets: () => request<import('../types').DatasetMeta[]>('/api/datasets'),
  getDataset: (id: string) => request<import('../types').DatasetMeta>(`/api/datasets/${id}`),
  validateDataset: (id: string) =>
    request<import('../types').DatasetValidateReport>(`/api/datasets/${id}/validate`, { method: 'POST' }),
  checkCompatibility: (datasetId: string, algorithmId: string) =>
    request<import('../types').CompatibilityCheck>(
      `/api/datasets/${datasetId}/compatibility/${algorithmId}`),
  deleteDataset: (id: string) => request<{ deleted: string }>(`/api/datasets/${id}`, { method: 'DELETE' }),

  // 实验
  getExperiments: () => request<import('../types').ExperimentSummary[]>('/api/experiments'),
  createExperiment: (payload: {
    algorithm_id: string;
    dataset_id: string;
    capability: string;
    params?: Record<string, unknown>;
    data_split?: import('../types').DataSplit;
    name?: string;
    timeout_seconds?: number;
  }) =>
    request<import('../types').ExperimentSummary>('/api/experiments', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteExperiment: (id: string) =>
    request<{ deleted: string }>(`/api/experiments/${id}`, { method: 'DELETE' }),
  uploadImport: (files: Record<string, File>, form: Record<string, string>) => {
    const fd = new FormData();
    Object.entries(files).forEach(([k, f]) => fd.append(k, f, f.name));
    Object.entries(form).forEach(([k, v]) => fd.append(k, v));
    return request<import('../types').ExperimentSummary>('/api/experiments/upload', { method: 'POST', body: fd });
  },

  // 任务
  getTaskStatus: (taskId: string) => request<import('../types').TaskStatus>(`/api/tasks/${taskId}/status`),
  getTaskLogs: (taskId: string, tail = 200) =>
    request<import('../types').TaskLogs>(`/api/tasks/${taskId}/logs?tail=${tail}`),
  cancelTask: (taskId: string) =>
    request<{ task_id: string; state: string }>(`/api/tasks/${taskId}/cancel`, { method: 'POST' }),

  // 结果
  getResult: (experimentId: string) =>
    request<import('../types').PortfolioResult>(`/api/results/${experimentId}`),
  getCurve: (experimentId: string) =>
    request<import('../types').CurveData>(`/api/results/${experimentId}/curve`),
  getWeights: (experimentId: string, tailDays = 60) =>
    request<{
      experiment_id: string;
      dates: string[];
      stock_weights: Record<string, number>[];
      cash_weights: number[];
      industry_weights: Record<string, number>[] | null;
      turnover: number[] | null;
      asset_label_mode: string;
    }>(`/api/results/${experimentId}/weights?tail_days=${tailDays}`),
  getSelection: (experimentId: string) =>
    request<{ experiment_id: string; selection: NonNullable<import('../types').PortfolioResult['stock_selection']> }>(
      `/api/results/${experimentId}/selection`),
  getMetrics: (experimentId: string) =>
    request<{ metrics: Record<string, number | null>; metric_assumptions: import('../types').MetricAssumptions }>(
      `/api/results/${experimentId}/metrics`),
  compare: (ids: string[]) =>
    request<import('../types').CompareResponse>(`/api/compare?ids=${encodeURIComponent(ids.join(','))}`),
};
