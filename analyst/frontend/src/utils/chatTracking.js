/** 判断任务查询错误是否表示任务已不存在（服务重启或任务被清理）。 */

const MISSING_TASK_PATTERNS = [/任务不存在/, /\b404\b/]

export function isMissingTaskError(error) {
  if (!error) return false
  const message = String(error.message || error)
  return MISSING_TASK_PATTERNS.some((pattern) => pattern.test(message))
}
