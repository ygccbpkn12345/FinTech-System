import { Badge, Col, Divider, Row, Space, Statistic, Tag, Typography } from 'antd'
import { FallOutlined, RiseOutlined, StockOutlined } from '@ant-design/icons'
import TerminalCard from './TerminalCard'
import { formatPercent } from '@/utils/signalUtils'

function formatNum(value, digits = 2) {
  return typeof value === 'number' && !Number.isNaN(value) ? value.toFixed(digits) : '--'
}

function MarketOverview({ stockInfo, stock, compact = false }) {
  const data = stockInfo ?? stock

  if (!data || typeof data !== 'object') {
    return (
      <TerminalCard
        title="行情层：标的基础数据"
        subtitle="Market Data Layer"
        extra="--"
        icon={<StockOutlined />}
        className={compact ? 'market-overview--compact' : ''}
      >
        <div className="cockpit-placeholder-body" style={{ minHeight: 80 }}>
          暂无行情数据
        </div>
      </TerminalCard>
    )
  }

  const change = typeof data.change === 'number' ? data.change : 0
  const isUp = change >= 0
  const code = data.code ?? '--'
  const name = data.name ?? '--'
  const industry = data.industry ?? '--'
  const volumeLabel =
    data.volumeLabel ??
    (typeof data.volume === 'string' ? data.volume : data.volume ? String(data.volume) : '--')
  const volatility =
    typeof data.volatility === 'number' ? `${data.volatility}%` : (data.volatilityLabel ?? '--')
  const pe = typeof data.pe === 'number' ? data.pe : (data.pe ?? '--')
  const marketCapLabel =
    data.marketCapLabel ?? (typeof data.marketCap === 'string' ? data.marketCap : '--')
  const analysisDate = data.analysisDate ?? '--'
  const amplitude =
    typeof data.amplitude === 'number' ? `${data.amplitude}%` : (data.amplitude ?? '--')

  return (
    <TerminalCard
      title="行情层：标的基础数据"
      subtitle="Market Data Layer"
      extra={code}
      icon={<StockOutlined />}
      accent="cyan"
      className={compact ? 'market-overview--compact' : ''}
    >
      <Row gutter={[16, 12]} align="middle" className="market-overview-row">
        <Col xs={24} md={8}>
          <div className="market-hero market-hero--compact">
            <div className="market-name-row">
              <Typography.Title level={4} className="market-name">
                {name}
              </Typography.Title>
              <Badge
                status={isUp ? 'error' : 'success'}
                text={isUp ? '上涨' : '下跌'}
                className="market-direction-badge"
              />
            </div>
            <Typography.Text type="secondary" className="market-code">
              {code} · {industry}
            </Typography.Text>
            <Statistic
              value={data.currentPrice}
              precision={2}
              valueStyle={{
                color: isUp ? 'var(--color-up)' : 'var(--color-down)',
                fontSize: 28,
                fontWeight: 700,
                fontFamily: 'var(--font-mono)',
              }}
              prefix={isUp ? <RiseOutlined /> : <FallOutlined />}
            />
            <Typography.Text className={`market-change ${isUp ? 'up' : 'down'}`}>
              {isUp && change !== 0 ? '+' : ''}
              {formatNum(change)} ({formatPercent(data.changePercent ?? 0)})
            </Typography.Text>
          </div>
        </Col>

        <Col xs={24} md={16}>
          <Row gutter={[12, 12]} className="market-stat-grid">
            {[
              { label: '最高', value: formatNum(data.high), color: 'var(--color-up)' },
              { label: '最低', value: formatNum(data.low), color: 'var(--color-down)' },
              { label: '成交量', value: volumeLabel },
              { label: '波动率', value: volatility, color: 'var(--accent-cyan)' },
              { label: 'PE', value: pe },
              { label: '市值', value: marketCapLabel, small: true },
            ].map((item) => (
              <Col xs={12} sm={8} key={item.label}>
                <div className="market-stat-card">
                  <Statistic
                    title={item.label}
                    value={item.value}
                    valueStyle={{
                      fontSize: item.small ? 13 : 16,
                      color: item.color ?? 'var(--text-primary)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  />
                </div>
              </Col>
            ))}
          </Row>
        </Col>
      </Row>

      <Divider className="market-divider" />

      <Space size={[8, 8]} wrap className="market-tags">
        <Tag className="tag-neutral">分析日 {analysisDate}</Tag>
        <Tag className="tag-neutral">振幅 {amplitude}</Tag>
        <Tag className="tag-cyan">实时行情快照</Tag>
      </Space>
    </TerminalCard>
  )
}

export default MarketOverview
