import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Alert,
  AutoComplete,
  Button,
  Col,
  Descriptions,
  DatePicker,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Upload,
  message,
} from 'antd'
import dayjs from 'dayjs'
import {
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  KeyOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
  StockOutlined,
  CloudDownloadOutlined,
} from '@ant-design/icons'
import PageShell from '@/components/PageShell'
import TerminalCard from '@/components/TerminalCard'
import DataStatusTag from '@/components/settings/DataStatusTag'
import {
  checkHealth,
  API_BASE_URL,
  USE_MOCK,
  SUPPORTED_STOCK_CODES,
} from '@/api/analysisApi'
import {
  fetchSymbolDataStatus,
  fetchSymbolList,
  fetchSystemConfig,
  saveSystemConfig,
  uploadStockData,
} from '@/api/configApi'
import {
  BASE_URL_PRESETS,
  DATA_TYPE_OPTIONS,
  DEEP_LLM_PRESETS,
  DEFAULT_LLM_CONFIG,
  QUICK_LLM_PRESETS,
  buildConfigSaveBody,
  hasUsableTushareToken,
  loadCachedSystemConfig,
} from '@/utils/systemConfig'
import { buildCrawlDashboardState, buildCrawlRequest } from '@/utils/crawlSync'

const { Password } = Input

function ModelPresetInput({ presets, value, onChange, placeholder }) {
  return (
    <AutoComplete
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      style={{ width: '100%' }}
      options={presets.map((item) => ({ value: item, label: item }))}
      filterOption={(inputValue, option) =>
        String(option?.value ?? '')
          .toLowerCase()
          .includes(String(inputValue ?? '').toLowerCase())
      }
    />
  )
}

function Settings() {
  const location = useLocation()
  const navigate = useNavigate()
  const [llmForm] = Form.useForm()
  const [uploadForm] = Form.useForm()

  const [loadingConfig, setLoadingConfig] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configSaveFeedback, setConfigSaveFeedback] = useState(null)
  const [maskedApiKey, setMaskedApiKey] = useState('')
  const [apiKeyInput, setApiKeyInput] = useState('')

  // 数据源配置
  const [dataSource, setDataSource] = useState('local_file')
  const [crawlUrl, setCrawlUrl] = useState('https://finance.eastmoney.com/')
  const [tushareToken, setTushareToken] = useState('')
  const [maskedTushareToken, setMaskedTushareToken] = useState('')
  const [tushareTokenConfigured, setTushareTokenConfigured] = useState(false)

  // 爬虫/API 模式下的股票代码输入
  const [symbolInput, setSymbolInput] = useState('')
  const [crawlDateRange, setCrawlDateRange] = useState([dayjs().subtract(1, 'year'), dayjs()])

  const [symbols, setSymbols] = useState([])
  const [symbolsLoading, setSymbolsLoading] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState(null)

  // 爬虫/API 加载状态
  const [fetchingData, setFetchingData] = useState(false)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerStatus, setDrawerStatus] = useState(null)
  const [drawerLoading, setDrawerLoading] = useState(false)

  const [healthLoading, setHealthLoading] = useState(false)
  const [configCheckLoading, setConfigCheckLoading] = useState(false)
  const [symbolsCheckLoading, setSymbolsCheckLoading] = useState(false)
  const [healthResult, setHealthResult] = useState(null)
  const [configCheckResult, setConfigCheckResult] = useState(null)
  const [symbolsCheckResult, setSymbolsCheckResult] = useState(null)

  const [activeTab, setActiveTab] = useState('upload')

  const applyConfigToForms = useCallback((config) => {
    llmForm.setFieldsValue({
      deepThinkLlm: config.llmConfig.deepThinkLlm,
      quickThinkLlm: config.llmConfig.quickThinkLlm,
      baseUrl: config.llmConfig.baseUrl,
      timeout: config.llmConfig.timeout,
      maxRetries: config.llmConfig.maxRetries,
    })
    setMaskedApiKey(config.llmConfig.maskedApiKey ?? '')
    setDataSource(config.dataSource ?? 'local_file')
    setCrawlUrl(config.crawlUrl ?? 'https://finance.eastmoney.com/')
    setMaskedTushareToken(config.maskedTushareToken ?? '')
    setTushareTokenConfigured(Boolean(config.tushareTokenConfigured))
  }, [llmForm])

  const loadConfig = useCallback(async () => {
    setLoadingConfig(true)
    try {
      const config = await fetchSystemConfig()
      applyConfigToForms(config)
    } catch (err) {
      const cached = loadCachedSystemConfig()
      applyConfigToForms(cached)
      message.warning(`读取配置失败，已使用本地默认值：${err.message}`)
    } finally {
      setLoadingConfig(false)
    }
  }, [applyConfigToForms])

  const refreshSymbols = useCallback(async () => {
    setSymbolsLoading(true)
    try {
      const list = await fetchSymbolList()
      setSymbols(list)
    } catch (err) {
      message.error(err.message)
    } finally {
      setSymbolsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConfig()
    refreshSymbols()
  }, [loadConfig, refreshSymbols])

  useEffect(() => {
    const state = location.state
    if (!state) return
    if (state.tab) setActiveTab(state.tab === 'paths' ? 'upload' : state.tab)
    if (state.symbol) {
      uploadForm.setFieldsValue({ symbol: state.symbol })
      setSymbolInput(state.symbol)
      setActiveTab('upload')
    }
  }, [location.state, uploadForm])

  // 保存数据源配置
  const handleSaveDataSource = async () => {
    try {
      const body = {
        dataSource: dataSource,
        crawlUrl: crawlUrl,
        tushareToken: tushareToken,
      }
      const config = await saveSystemConfig(body)
      applyConfigToForms(config)
      setTushareToken('')
      message.success('数据源配置已保存并生效')
      if (config) return

      // Legacy compatibility request retained unreachable until the settings
      // page is split into smaller components.
      const response = await fetch('/api/config/data-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error('保存失败')
      message.success('数据源配置已保存')
    } catch (err) {
      message.error(err.message || '保存数据源配置失败')
    }
  }

  // 执行爬虫/API 获取数据
  const handleFetchData = async () => {
    console.log('🔵 handleFetchData 被调用了')
    try {
      const symbol = symbolInput.trim()
      console.log('🔵 股票代码:', symbol)
      if (!symbol) {
        message.warning('请先输入股票代码')
        return
      }

      setFetchingData(true)
      setUploadStatus(null)

      console.log('🔵 发送请求到 /api/data/fetch')
      const response = await fetch('/api/data/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildCrawlRequest({
          symbol: symbol,
          dataSource: dataSource,
          crawlUrl: crawlUrl,
          tushareToken: tushareToken,
          startDate: crawlDateRange?.[0]?.format('YYYY-MM-DD'),
          endDate: crawlDateRange?.[1]?.format('YYYY-MM-DD'),
        })),
      })

      console.log('🔵 收到响应')
      const result = await response.json()
      console.log('🔵 结果:', result)
      if (result.status === 'ok' || result.status === 'partial') {
        if (result.status === 'partial') {
          message.warning(result.message || `部分数据获取失败：${(result.failedModules || []).join('、')}`)
        } else {
          message.success(`成功获取 ${symbol} 的数据，共 ${result.count || 0} 条`)
        }
        const status = await fetchSymbolDataStatus(symbol)
        setUploadStatus(status)
        await refreshSymbols()
        uploadForm.setFieldsValue({ symbol: symbol })
        navigate('/dashboard', {
          state: buildCrawlDashboardState(
            { ...result, dataStatus: status },
            symbol,
          ),
        })
      } else {
        message.error(result.message || '获取数据失败')
      }
    } catch (err) {
      console.error('🔴 错误:', err)
      message.error(err.message || '获取数据失败')
    } finally {
      setFetchingData(false)
    }
  }

  const handleSaveConfig = async () => {
    setConfigSaveFeedback(null)
    try {
      const llmConfig = await llmForm.validateFields()
      setSavingConfig(true)

      const cached = loadCachedSystemConfig()
      const body = buildConfigSaveBody({ dataConfig: cached.dataConfig, llmConfig, apiKeyInput })
      const config = await saveSystemConfig(body)
      applyConfigToForms(config)
      setApiKeyInput('')
      const feedback = config.apiKeyConfigured
        ? { type: 'success', text: '模型配置已保存，下次调用生效。' }
        : { type: 'warning', text: '模型参数已保存，但尚未配置 API Key；请填写密钥后再次保存。' }
      setConfigSaveFeedback(feedback)
      message[feedback.type](feedback.text)
    } catch (err) {
      if (err?.errorFields) {
        setActiveTab('llm')
        const text = '请补全标红的模型配置项后再保存。'
        setConfigSaveFeedback({ type: 'error', text })
        message.error(text)
        return
      }
      const text = err.message || '保存配置失败'
      setConfigSaveFeedback({ type: 'error', text })
      message.error(text)
    } finally {
      setSavingConfig(false)
    }
  }

  const handleClearCredential = async (field) => {
    const label = field === 'apiKey' ? 'DeepSeek API Key' : 'Tushare Token'
    if (!window.confirm(`确认清除已保存的 ${label}？`)) return
    try {
      setSavingConfig(true)
      const config = await saveSystemConfig(
        field === 'apiKey' ? { clearApiKey: true } : { clearTushareToken: true },
      )
      applyConfigToForms(config)
      if (field === 'apiKey') setApiKeyInput('')
      if (field === 'tushareToken') setTushareToken('')
      message.success(`${label} 已清除`)
    } catch (err) {
      message.error(err.message || `清除 ${label} 失败`)
    } finally {
      setSavingConfig(false)
    }
  }

  const handleUpload = async () => {
    try {
      const values = await uploadForm.validateFields()
      if (!uploadFile) {
        message.warning('请选择上传文件')
        return
      }
      setUploading(true)
      setUploadStatus(null)
      const res = await uploadStockData({
        symbol: values.symbol,
        name: values.name,
        dataType: values.dataType,
        file: uploadFile,
      })
      message.success(res?.message || '上传成功')
      const status = await fetchSymbolDataStatus(values.symbol)
      setUploadStatus(status)
      await refreshSymbols()
      uploadForm.setFieldValue('symbol', values.symbol)
    } catch (err) {
      if (err?.errorFields) return
      message.error(err.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const openSymbolStatus = async (symbol) => {
    setDrawerOpen(true)
    setDrawerLoading(true)
    setDrawerStatus(null)
    try {
      const status = await fetchSymbolDataStatus(symbol)
      setDrawerStatus(status)
    } catch (err) {
      message.error(err.message)
    } finally {
      setDrawerLoading(false)
    }
  }

  const handleHealthCheck = async () => {
    setHealthLoading(true)
    setHealthResult(null)
    try {
      const res = await checkHealth()
      setHealthResult({ ok: true, data: res })
    } catch (err) {
      setHealthResult({ ok: false, message: err.message })
    } finally {
      setHealthLoading(false)
    }
  }

  const handleConfigCheck = async () => {
    setConfigCheckLoading(true)
    setConfigCheckResult(null)
    try {
      const res = await fetchSystemConfig()
      setConfigCheckResult({ ok: true, data: res })
    } catch (err) {
      setConfigCheckResult({ ok: false, message: err.message })
    } finally {
      setConfigCheckLoading(false)
    }
  }

  const handleSymbolsCheck = async () => {
    setSymbolsCheckLoading(true)
    setSymbolsCheckResult(null)
    try {
      const res = await fetchSymbolList()
      setSymbolsCheckResult({ ok: true, data: res })
      setSymbols(res)
    } catch (err) {
      setSymbolsCheckResult({ ok: false, message: err.message })
    } finally {
      setSymbolsCheckLoading(false)
    }
  }

  const symbolColumns = useMemo(
    () => [
      { title: '股票代码', dataIndex: 'symbol', key: 'symbol', width: 100 },
      { title: '股票名称', dataIndex: 'name', key: 'name', width: 120 },
      {
        title: '技术指标',
        dataIndex: 'technicalIndicators',
        key: 'technicalIndicators',
        render: (v) => <DataStatusTag status={v} />,
      },
      {
        title: '新闻',
        dataIndex: 'news',
        key: 'news',
        render: (v) => <DataStatusTag status={v} />,
      },
      {
        title: '基本面',
        dataIndex: 'fundamentals',
        key: 'fundamentals',
        render: (v) => <DataStatusTag status={v} />,
      },
      {
        title: 'result',
        dataIndex: 'result',
        key: 'result',
        render: (v) => <DataStatusTag status={v} />,
      },
      {
        title: 'train 记忆',
        dataIndex: 'trainMemory',
        key: 'trainMemory',
        render: (v) => <DataStatusTag status={v} optional />,
      },
      {
        title: 'test 记忆',
        dataIndex: 'testMemory',
        key: 'testMemory',
        render: (v) => <DataStatusTag status={v} optional />,
      },
      {
        title: '是否可分析',
        dataIndex: 'available',
        key: 'available',
        width: 110,
        render: (v, row) => {
          const coreMissing = ['technicalIndicators', 'news', 'fundamentals', 'result'].filter(
            (key) => row[key] === 'missing',
          )
          if (v && coreMissing.length > 0) {
            return <Tag color="warning">核心数据不全</Tag>
          }
          return v ? (
            <Tag color="success">可分析</Tag>
          ) : (
            <Tag color="error">不可分析</Tag>
          )
        },
      },
      {
        title: '操作',
        key: 'action',
        width: 120,
        render: (_, row) => (
          <Button type="link" size="small" onClick={() => openSymbolStatus(row.symbol)}>
            查看数据状态
          </Button>
        ),
      },
    ],
    [],
  )

  // 判断当前数据源模式
  const showCrawlInput = dataSource === 'baostock'
  const showTushareInput = dataSource === 'tushare'
  const isLocalFile = dataSource === 'local_file'
  const tushareTokenUsable = hasUsableTushareToken({
    tushareToken,
    tushareTokenConfigured,
  })

  const tabItems = [
    {
      key: 'upload',
      label: '数据接入',
      children: (
        <TerminalCard
          title="数据接入配置"
          subtitle="Data Source & Upload"
          icon={<CloudUploadOutlined />}
          accent="gold"
        >
          {/* 数据源选择区块 */}
          <div style={{ marginBottom: 24, padding: '16px', background: '#f5f5f5', borderRadius: 8 }}>
            <div style={{ marginBottom: 12, fontWeight: 'bold' }}>
              <DatabaseOutlined style={{ marginRight: 8 }} />
              数据源选择
            </div>
            <Row gutter={16} align="middle">
              <Col xs={24} md={6}>
                <span style={{ marginRight: 8 }}>数据源：</span>
                <Select
                  value={dataSource}
                  onChange={setDataSource}
                  style={{ width: '100%' }}
                  options={[
                    { value: 'local_file', label: '📁 本地文件' },
                    { value: 'baostock', label: '🌐 爬虫抓取' },
                    { value: 'tushare', label: '🔗 API调用' },
                  ]}
                />
              </Col>

              {showCrawlInput && (
                <Col xs={24} md={12}>
                  <Input
                    value={crawlUrl}
                    onChange={(e) => setCrawlUrl(e.target.value)}
                    placeholder="爬虫目标网址 (默认: https://finance.eastmoney.com/)"
                    style={{ width: '100%' }}
                    addonBefore="目标网址"
                  />
                </Col>
              )}

              {showTushareInput && (
                <Col xs={24} md={12}>
                  <Input.Password
                    value={tushareToken}
                    onChange={(e) => setTushareToken(e.target.value)}
                    placeholder="请输入 Tushare Token"
                    style={{ width: '100%' }}
                    addonBefore="API Token"
                  />
                  {maskedTushareToken && (
                    <Space direction="vertical" size={4}>
                      <span className="settings-masked-key">
                        已保存（脱敏）：<code>{maskedTushareToken}</code>
                      </span>
                      <Button danger size="small" onClick={() => handleClearCredential('tushareToken')}>
                        清除已保存 Token
                      </Button>
                    </Space>
                  )}
                </Col>
              )}

              <Col xs={24} md={6} style={{ textAlign: 'right' }}>
                <Button
                  type="primary"
                  size="small"
                  icon={<SaveOutlined />}
                  onClick={handleSaveDataSource}
                >
                  保存数据源配置
                </Button>
              </Col>
            </Row>
            <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
              当前数据源：{dataSource === 'local_file' ? '📁 本地文件' : dataSource === 'baostock' ? '🌐 爬虫抓取' : '🔗 API调用'}
            </div>
          </div>

          <Divider />

          {/* 根据数据源显示不同内容 */}
          {isLocalFile ? (
            // 本地文件模式：显示上传表单
            <>
              <Form form={uploadForm} layout="vertical" className="settings-form">
                <Row gutter={16}>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="symbol"
                      label="股票代码"
                      rules={[{ required: true, message: '请输入股票代码' }]}
                    >
                      <Input placeholder="如 000063" prefix={<StockOutlined />} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item name="name" label="股票名称（可选）">
                      <Input placeholder="如 中兴通讯" />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item
                      name="dataType"
                      label="数据类型"
                      rules={[{ required: true, message: '请选择数据类型' }]}
                    >
                      <Select placeholder="选择 dataType" options={DATA_TYPE_OPTIONS} />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item label="上传文件" required>
                  <Upload
                    beforeUpload={(file) => {
                      setUploadFile(file)
                      return false
                    }}
                    maxCount={1}
                    onRemove={() => setUploadFile(null)}
                  >
                    <Button icon={<CloudUploadOutlined />}>选择文件</Button>
                  </Upload>
                </Form.Item>
                <Space>
                  <Button type="primary" loading={uploading} onClick={handleUpload}>
                    上传数据
                  </Button>
                  <Button
                    onClick={async () => {
                      const symbol = uploadForm.getFieldValue('symbol')
                      if (!symbol) {
                        message.warning('请先输入股票代码')
                        return
                      }
                      const status = await fetchSymbolDataStatus(symbol)
                      setUploadStatus(status)
                    }}
                  >
                    刷新数据状态
                  </Button>
                </Space>
              </Form>
            </>
          ) : (
            // 爬虫/API 模式：显示获取数据按钮
            <>
              <div style={{ padding: '16px', background: showCrawlInput ? '#f6ffed' : '#e6f7ff', borderRadius: 8, border: showCrawlInput ? '1px solid #b7eb8f' : '1px solid #91d5ff' }}>
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <div>
                    {showCrawlInput ? (
                      <Tag color="green">🌐 爬虫模式</Tag>
                    ) : (
                      <Tag color="blue">🔗 API模式</Tag>
                    )}
                    <span style={{ marginLeft: 8 }}>
                      {showCrawlInput
                        ? '系统将从 Baostock 自动获取数据'
                        : '系统将通过 Tushare API 获取数据'}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: '#888' }}>
                    {showCrawlInput
                      ? `数据源：Baostock`
                      : `Token：${tushareTokenUsable ? '已配置 ✅' : '未配置 ⚠️'}`}
                  </div>
                  <div>
                    <span style={{ marginRight: 8 }}>股票代码：</span>
                    <Input
                      value={symbolInput}
                      onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
                      placeholder="如 000063"
                      style={{ width: 150 }}
                      prefix={<StockOutlined />}
                    />
                  </div>
                  <div>
                    <span style={{ marginRight: 8 }}>爬取时间：</span>
                    <DatePicker.RangePicker
                      value={crawlDateRange}
                      onChange={(dates) => setCrawlDateRange(dates)}
                      allowClear={false}
                      disabledDate={(current) => current && current.isAfter(dayjs(), 'day')}
                    />
                  </div>
                  <Button
                    type="primary"
                    icon={<CloudDownloadOutlined />}
                    loading={fetchingData}
                    onClick={handleFetchData}
                    disabled={showTushareInput && !tushareTokenUsable}
                  >
                    {showCrawlInput ? '爬取数据' : '获取数据'}
                  </Button>
                </Space>
              </div>
            </>
          )}

          {uploadStatus && (
            <Alert
              style={{ marginTop: 16 }}
              type={uploadStatus.available ? 'success' : 'warning'}
              showIcon
              message={
                uploadStatus.available
                  ? `${uploadStatus.symbol} 数据齐全，可分析`
                  : `${uploadStatus.symbol} 仍缺少：${(uploadStatus.missing ?? []).join('、') || '部分数据'}`
              }
            />
          )}
        </TerminalCard>
      ),
    },
    {
      key: 'llm',
      label: '大模型配置',
      forceRender: true,
      children: (
        <TerminalCard
          title="模型与 API"
          subtitle="LLM Configuration"
          icon={<RobotOutlined />}
          accent="cyan"
        >
          <Form
            form={llmForm}
            layout="vertical"
            initialValues={DEFAULT_LLM_CONFIG}
            className="settings-form"
          >
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item
                  name="deepThinkLlm"
                  label="deep_think_llm"
                  tooltip="思考模型：经理、风控、最终决策者等深度推理节点"
                  rules={[{ required: true }]}
                >
                  <ModelPresetInput presets={DEEP_LLM_PRESETS} placeholder="选择深度思考模型" />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="quickThinkLlm"
                  label="quick_think_llm"
                  tooltip="快速模型：五位分析师等节点"
                  rules={[{ required: true }]}
                >
                  <ModelPresetInput presets={QUICK_LLM_PRESETS} placeholder="选择快速模型" />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item
              name="baseUrl"
              label="base_url"
              rules={[{ required: true, message: '请输入 base_url' }]}
            >
              <ModelPresetInput presets={BASE_URL_PRESETS} placeholder="选择 API Base URL" />
            </Form.Item>

            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item label="api_key">
                  <Password
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    placeholder="留空则不修改后端已保存密钥"
                    autoComplete="new-password"
                    prefix={<KeyOutlined />}
                  />
                  {maskedApiKey && (
                    <Button danger size="small" onClick={() => handleClearCredential('apiKey')}>
                      清除已保存 API Key
                    </Button>
                  )}
                  {maskedApiKey ? (
                    <div className="settings-masked-key">
                      后端已保存（脱敏）：<code>{maskedApiKey}</code>
                    </div>
                  ) : (
                    <div className="settings-masked-key settings-hint">
                      尚未保存 API Key，请填写后点击“保存配置”。
                    </div>
                  )}
                </Form.Item>
              </Col>
              <Col xs={24} md={5}>
                <Form.Item name="timeout" label="timeout" rules={[{ required: true }]}>
                  <InputNumber min={10} max={600} style={{ width: '100%' }} addonAfter="秒" />
                </Form.Item>
              </Col>
              <Col xs={24} md={5}>
                <Form.Item name="maxRetries" label="maxRetries" rules={[{ required: true }]}>
                  <InputNumber min={0} max={10} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </TerminalCard>
      ),
    },
    {
      key: 'symbols',
      label: '股票数据状态',
      children: (
        <TerminalCard
          title="股票列表"
          subtitle="Symbol Registry"
          icon={<StockOutlined />}
          accent="blue"
          extra={
            <Button size="small" icon={<ReloadOutlined />} onClick={refreshSymbols} loading={symbolsLoading}>
              刷新
            </Button>
          }
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="「是否可分析」只看四类核心数据；train/test 记忆库显示「未配置」不代表不能分析。"
          />
          <Table
            size="small"
            rowKey="symbol"
            loading={symbolsLoading}
            columns={symbolColumns}
            dataSource={symbols}
            scroll={{ x: 1100 }}
            pagination={{ pageSize: 8, showSizeChanger: false }}
          />
          {!symbols.length && (
            <Alert
              type="info"
              showIcon
              message={`后端暂无列表，fallback 默认：${SUPPORTED_STOCK_CODES.join('、')}`}
            />
          )}
        </TerminalCard>
      ),
    },
    {
      key: 'connectivity',
      label: '系统连通性',
      children: (
        <Row gutter={[12, 12]}>
          <Col xs={24} lg={14}>
            <TerminalCard title="环境信息" subtitle="Runtime" icon={<ApiOutlined />} accent="cyan">
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="API 地址">
                  <code>{API_BASE_URL}</code>
                </Descriptions.Item>
                <Descriptions.Item label="前端 Mock">
                  <Tag>{USE_MOCK ? 'true' : 'false'}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="默认 fallback 股票">
                  {SUPPORTED_STOCK_CODES.join('、')}
                </Descriptions.Item>
              </Descriptions>
            </TerminalCard>
          </Col>
          <Col xs={24} lg={10}>
            <TerminalCard title="连通性探测" subtitle="Health Checks" icon={<ApiOutlined />}>
              <Space direction="vertical" style={{ width: '100%' }} size="middle">
                <Button block loading={healthLoading} onClick={handleHealthCheck}>
                  检查后端健康 GET /api/health
                </Button>
                <Button block loading={configCheckLoading} onClick={handleConfigCheck}>
                  检查配置 GET /api/config
                </Button>
                <Button block loading={symbolsCheckLoading} onClick={handleSymbolsCheck}>
                  检查可用股票 GET /api/symbols
                </Button>

                {healthResult?.ok && (
                  <Alert
                    type="success"
                    showIcon
                    icon={<CheckCircleOutlined />}
                    message="健康检查成功"
                    description={JSON.stringify(healthResult.data)}
                  />
                )}
                {healthResult && !healthResult.ok && (
                  <Alert type="error" showIcon icon={<CloseCircleOutlined />} message={healthResult.message} />
                )}
                {configCheckResult?.ok && (
                  <Alert
                    type="success"
                    showIcon
                    message="配置读取成功"
                    description={`模型=${configCheckResult.data?.llmConfig?.deepThinkLlm ?? '--'}`}
                  />
                )}
                {configCheckResult && !configCheckResult.ok && (
                  <Alert type="error" showIcon message={configCheckResult.message} />
                )}
                {symbolsCheckResult?.ok && (
                  <Alert
                    type="success"
                    showIcon
                    message={`股票列表 OK（${symbolsCheckResult.data?.length ?? 0} 条）`}
                  />
                )}
                {symbolsCheckResult && !symbolsCheckResult.ok && (
                  <Alert type="error" showIcon message={symbolsCheckResult.message} />
                )}
              </Space>
            </TerminalCard>
          </Col>
        </Row>
      ),
    },
  ]

  return (
    <PageShell
      title="系统配置"
      subtitle="数据接入 · 模型 · 连通性"
      breadcrumbItems={[{ title: '工作台' }, { title: '系统配置' }]}
      extra={
        <Space>
          <Tooltip title="从后端重新加载配置">
            <Button icon={<ReloadOutlined />} loading={loadingConfig} onClick={loadConfig}>
              重新加载
            </Button>
          </Tooltip>
          <Button type="primary" icon={<SaveOutlined />} loading={savingConfig} onClick={handleSaveConfig}>
            保存配置
          </Button>
        </Space>
      }
    >
      {configSaveFeedback && (
        <Alert
          type={configSaveFeedback.type}
          message={configSaveFeedback.text}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        className="settings-tabs"
      />

      <Drawer
        title="股票数据状态"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={480}
      >
        {drawerLoading ? (
          <Alert message="加载中…" type="info" />
        ) : drawerStatus ? (
          <>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="股票">{drawerStatus.symbol}</Descriptions.Item>
              <Descriptions.Item label="可分析">
                {drawerStatus.available ? (
                  <Tag color="success">是</Tag>
                ) : (
                  <Tag color="error">否</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="缺失项">
                {(drawerStatus.missing ?? []).length
                  ? drawerStatus.missing.join('、')
                  : '无'}
              </Descriptions.Item>
            </Descriptions>
            <Divider />
            <Space wrap>
              <DataStatusTag status={drawerStatus.technicalIndicators} />
              <span>技术指标</span>
              <DataStatusTag status={drawerStatus.news} />
              <span>新闻</span>
              <DataStatusTag status={drawerStatus.fundamentals} />
              <span>基本面</span>
            </Space>
          </>
        ) : null}
      </Drawer>
    </PageShell>
  )
}

export default Settings
