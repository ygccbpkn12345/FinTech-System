const META = {
  pending: { kind: 'info', message: '反思正在后台排队生成。' },
  running: { kind: 'info', message: '反思正在后台生成，不影响主分析结果。' },
  completed: { kind: 'success', message: '反思记忆已生成。' },
  failed: { kind: 'error', message: '反思生成失败，可稍后重试或检查后端日志。' },
  not_applicable: { kind: 'warning', message: '当天尚无事后结果，本次不执行环境模拟和反思。' },
}

export function describeReflectionLifecycle(value = {}) {
  return META[value.status] ?? { kind: 'info', message: '正在查询反思生成状态。' }
}
