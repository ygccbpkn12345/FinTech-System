import {
  Alert,
  Button,
  DatePicker,
  Divider,
  Flex,
  Input,
  Segmented,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  CalendarOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  SearchOutlined,
  SettingOutlined,
  StockOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  SUPPORTED_STOCK_HINT,
  normalizeStockCodeInput,
} from '@/api/analysisApi'
import AnalysisStatusAlert from './AnalysisStatusAlert'
import TerminalCard from './TerminalCard'
import DataStatusTag from './settings/DataStatusTag'

function StockInputBar({
  stockCode,
  onStockCodeChange,
  analysisDate,
  onDateChange,
  onAnalyze,
  loading,
  analyzed,
  error,
  currentNode,
  progress,
  taskStatus,
  onCloseError,
  quickPickCodes = [],
  dataStatus,
  dataStatusLoading,
  onCheckDataStatus,
}) {
  const navigate = useNavigate()
  const normalizedCode = normalizeStockCodeInput(stockCode)
  const quickOptions = quickPickCodes.length
    ? quickPickCodes
    : ['000063', '000157', '000333', '000921', '000988']

  const canAnalyze =
    dataStatus == null ? true : dataStatus.available !== false

  return (
    <TerminalCard
      title="输入层：分析控制台"
      subtitle="Analysis Console"
      extra="Input Layer"
      icon={<StockOutlined />}
      accent="cyan"
      className="stock-input-bar"
    >
      <Flex wrap gap={12} align="center" className="stock-input-row">
        <Space size={8}>
          <Typography.Text type="secondary" className="query-label">
            股票代码
          </Typography.Text>
          <Input
            value={stockCode}
            onChange={(e) => onStockCodeChange(e.target.value.toUpperCase())}
            placeholder="如 000063"
            style={{ width: 140 }}
            prefix={<SearchOutlined style={{ color: 'var(--text-muted)' }} />}
            onPressEnter={loading || !canAnalyze ? undefined : onAnalyze}
            disabled={loading}
          />
        </Space>

        <Space size={8}>
          <Typography.Text type="secondary" className="query-label">
            分析日期
          </Typography.Text>
          <DatePicker
            value={analysisDate}
            onChange={(d) => d && onDateChange(d)}
            style={{ width: 150 }}
            allowClear={false}
            disabled={loading}
            suffixIcon={<CalendarOutlined />}
          />
        </Space>

        <Button
          icon={<DatabaseOutlined />}
          loading={dataStatusLoading}
          disabled={loading || !normalizedCode}
          onClick={onCheckDataStatus}
        >
          查看数据状态
        </Button>

        <Tooltip
          title={
            canAnalyze
              ? '启动 Multi-Agent 全流程分析'
              : '当前股票数据不完整，请先上传数据'
          }
        >
          <Button
            type="primary"
            size="middle"
            icon={<PlayCircleOutlined />}
            loading={loading}
            disabled={loading || !canAnalyze}
            onClick={onAnalyze}
            className="stock-analyze-btn"
          >
            {loading ? '分析中…' : '启动分析'}
          </Button>
        </Tooltip>

        {analyzed && !loading && (
          <Tag className="tag-cyan stock-done-tag">
            分析完成 · {analysisDate.format('YYYY-MM-DD')}
          </Tag>
        )}
      </Flex>

      {dataStatus && (
        <Alert
          style={{ marginTop: 12 }}
          type={dataStatus.available ? 'success' : 'warning'}
          showIcon
          message={
            dataStatus.available
              ? `${dataStatus.symbol} 数据就绪，可启动分析`
              : `${dataStatus.symbol} 数据不完整`
          }
          description={
            !dataStatus.available ? (
              <Space direction="vertical" size={4}>
                <span>
                  缺失核心数据：{(dataStatus.missing ?? []).join('、') || '未知项'}
                </span>
                <Button
                  type="link"
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() =>
                    navigate('/settings', { state: { tab: 'upload', symbol: normalizedCode } })
                  }
                  style={{ padding: 0 }}
                >
                  去系统配置页上传数据
                </Button>
              </Space>
            ) : null
          }
        />
      )}

      <Divider className="stock-input-divider" />

      <div className="stock-quick-pick-wrap">
        <Typography.Text type="secondary" className="stock-quick-label">
          快捷选股
        </Typography.Text>
        <Segmented
          className="stock-quick-pick"
          options={quickOptions.map((code) => ({ label: code, value: code }))}
          value={quickOptions.includes(normalizedCode) ? normalizedCode : undefined}
          onChange={(v) => onStockCodeChange(v)}
          disabled={loading}
          size="small"
        />
        {dataStatus && (
          <DataStatusTag status={dataStatus.available ? 'ready' : 'missing'} />
        )}
      </div>

      <Alert type="info" showIcon message={SUPPORTED_STOCK_HINT} className="stock-hint-alert" />

      <AnalysisStatusAlert
        loading={loading}
        analyzed={analyzed}
        error={error}
        currentNode={currentNode}
        progress={progress}
        taskStatus={taskStatus}
        onCloseError={onCloseError}
      />
    </TerminalCard>
  )
}

export default StockInputBar