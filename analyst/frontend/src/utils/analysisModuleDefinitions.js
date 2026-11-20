export const ANALYSIS_MODULES = [
  ['market_analyst', '市场分析师'],
  ['news_analyst', '新闻分析师'],
  ['fundamentals_analyst', '基本面分析师'],
  ['industry_analyst', '行业分析师'],
  ['momentum_analyst', '动量分析师'],
  ['router', '动态路由'],
  ['manager', '投资经理'],
  ['risk_manager', '风险经理'],
  ['final_decision', '最终决策'],
]

export const VISIBLE_ANALYSIS_MODULES = ANALYSIS_MODULES.map(([name]) => name)
