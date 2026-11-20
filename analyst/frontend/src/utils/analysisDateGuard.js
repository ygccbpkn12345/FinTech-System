export function checkAnalysisDateAvailability(selectedDate, availableDates = []) {
  if (availableDates.includes(selectedDate)) return { allowed: true, message: '' }
  return {
    allowed: false,
    message: `分析日期 ${selectedDate} 没有可用数据，请重新选择日期`,
  }
}
