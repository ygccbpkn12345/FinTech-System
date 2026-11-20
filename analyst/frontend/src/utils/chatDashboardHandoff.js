/** 解析从聊天结果卡跳转到工作台时携带的任务引用。 */

export function resolveChatHandoff(state) {
  if (!state || typeof state !== 'object') return null
  const taskId = state.taskId
  if (!taskId || !state.fromChat) return null

  return {
    taskId: String(taskId),
    shouldLoadResult: true,
    shouldStartAnalysis: false,
  }
}
