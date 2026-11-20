import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
} from 'antd'
import { DeleteOutlined, EyeOutlined, HistoryOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import PageShell from '@/components/PageShell'
import TerminalCard from '@/components/TerminalCard'
import { getActionTheme } from '@/utils/signalUtils'
import {
  clearHistory,
  getHistoryRecordById,
  loadHistory,
  queueLoadRecord,
} from '@/utils/analysisStorage'

function History() {
  const navigate = useNavigate()
  const [records, setRecords] = useState(() => loadHistory())
  const [searchCode, setSearchCode] = useState('')
  const [actionFilter, setActionFilter] = useState('all')
  const [detailId, setDetailId] = useState(null)

  useEffect(() => {
    setRecords(loadHistory())
  }, [])

  const detailRecord = useMemo(
    () => (detailId ? getHistoryRecordById(detailId) : null),
    [detailId, records],
  )

  const actionOptions = useMemo(() => {
    const actions = [...new Set(records.map((r) => r.action).filter(Boolean))]
    return [{ label: '全部动作', value: 'all' }, ...actions.map((a) => ({ label: a, value: a }))]
  }, [records])

  const filteredRecords = useMemo(() => {
    return records.filter((r) => {
      const matchCode =
        !searchCode.trim() ||
        r.stockCode?.toLowerCase().includes(searchCode.trim().toLowerCase()) ||
        r.stockName?.toLowerCase().includes(searchCode.trim().toLowerCase())
      const matchAction = actionFilter === 'all' || r.action === actionFilter
      return matchCode && matchAction
    })
  }, [records, searchCode, actionFilter])

  const handleClear = () => {
    clearHistory()
    setRecords([])
    setDetailId(null)
  }

  const handleLoadToWorkbench = (id) => {
    if (queueLoadRecord(id)) {
      navigate('/dashboard')
    }
  }

  const columns = [
    {
      title: '股票代码',
      dataIndex: 'stockCode',
      key: 'stockCode',
      width: 100,
      render: (code) => <span className="mono-text">{code}</span>,
    },
    {
      title: '股票名称',
      dataIndex: 'stockName',
      key: 'stockName',
      width: 120,
    },
    {
      title: '分析日期',
      dataIndex: 'analysisDate',
      key: 'analysisDate',
      width: 110,
    },
    {
      title: '最终动作',
      dataIndex: 'action',
      key: 'action',
      width: 110,
      render: (action) => {
        const theme = getActionTheme(action)
        return <Tag className={theme.tagClass}>{action}</Tag>
      },
    },
    {
      title: '建议仓位',
      dataIndex: 'position',
      key: 'position',
      width: 90,
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      key: 'confidence',
      width: 80,
      render: (v) => `${Math.round((v ?? 0) * 100)}%`,
    },
    {
      title: '风险评分',
      dataIndex: 'riskScore',
      key: 'riskScore',
      width: 90,
    },
    {
      title: '完成时间',
      dataIndex: 'completedAt',
      key: 'completedAt',
      width: 160,
      render: (v) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '--'),
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 100,
      render: (source) => (
        <Tag className={source === 'real_model' ? 'tag-cyan' : 'tag-neutral'}>
          {source === 'real_model' ? '真实模型' : 'Mock'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => setDetailId(record.id)}
          >
            查看详情
          </Button>
          <Button type="link" size="small" onClick={() => handleLoadToWorkbench(record.id)}>
            加载工作台
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <PageShell
      title="历史记录"
      subtitle="本地分析决策归档 · LocalStorage"
      breadcrumbItems={[{ title: '工作台' }, { title: '历史记录' }]}
      extra={
        <Tag className="tag-cyan">{filteredRecords.length} 条记录</Tag>
      }
    >
      <Row gutter={[12, 12]} className="page-stat-row">
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} className="page-stat-card">
            <Statistic title="总记录" value={records.length} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} className="page-stat-card">
            <Statistic
              title="真实模型"
              value={records.filter((r) => r.source === 'real_model').length}
              valueStyle={{ color: 'var(--accent-cyan)' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} className="page-stat-card">
            <Statistic title="筛选结果" value={filteredRecords.length} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} className="page-stat-card">
            <Statistic
              title="最近分析"
              value={
                records[0]?.completedAt
                  ? dayjs(records[0].completedAt).format('MM-DD')
                  : '--'
              }
            />
          </Card>
        </Col>
      </Row>

      <TerminalCard
        title="历史层：分析记录"
        subtitle="Analysis History"
        extra="History Layer"
        icon={<HistoryOutlined />}
        accent="blue"
      >
        <div className="history-toolbar">
          <Input
            allowClear
            placeholder="按股票代码或名称搜索"
            value={searchCode}
            onChange={(e) => setSearchCode(e.target.value)}
            style={{ width: 220 }}
          />
          <Select
            value={actionFilter}
            onChange={setActionFilter}
            options={actionOptions}
            style={{ width: 140 }}
          />
          <Popconfirm
            title="确认清空全部历史记录？"
            onConfirm={handleClear}
            okText="清空"
            cancelText="取消"
            disabled={!records.length}
          >
            <Button danger icon={<DeleteOutlined />} disabled={!records.length}>
              清空历史
            </Button>
          </Popconfirm>
        </div>

        {filteredRecords.length ? (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={filteredRecords}
            size="small"
            scroll={{ x: 1200 }}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            className="history-table"
          />
        ) : (
          <Empty
            image={<HistoryOutlined style={{ fontSize: 48, color: 'var(--text-muted)' }} />}
            description={
              <span className="empty-desc-block">
                暂无分析记录，完成一次真实分析后将在此处展示。
              </span>
            }
          />
        )}
      </TerminalCard>

      <Drawer
        title={`分析详情 · ${detailRecord?.stockName ?? ''}`}
        open={Boolean(detailRecord)}
        onClose={() => setDetailId(null)}
        width={640}
        className="history-detail-drawer"
      >
        {detailRecord && (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="股票代码">{detailRecord.stockCode}</Descriptions.Item>
              <Descriptions.Item label="股票名称">{detailRecord.stockName}</Descriptions.Item>
              <Descriptions.Item label="分析日期">{detailRecord.analysisDate}</Descriptions.Item>
              <Descriptions.Item label="最终动作">{detailRecord.action}</Descriptions.Item>
              <Descriptions.Item label="建议仓位">{detailRecord.position}</Descriptions.Item>
              <Descriptions.Item label="置信度">
                {Math.round((detailRecord.confidence ?? 0) * 100)}%
              </Descriptions.Item>
              <Descriptions.Item label="风险评分">{detailRecord.riskScore}</Descriptions.Item>
              <Descriptions.Item label="来源">
                {detailRecord.source === 'real_model' ? '真实模型' : 'Mock'}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间" span={2}>
                {dayjs(detailRecord.completedAt).format('YYYY-MM-DD HH:mm:ss')}
              </Descriptions.Item>
            </Descriptions>

            {detailRecord.snapshot?.finalDecision?.coreReason && (
              <TerminalCard title="核心依据" className="history-detail-section">
                <p className="detail-text">{detailRecord.snapshot.finalDecision.coreReason}</p>
              </TerminalCard>
            )}

            <Button type="primary" block onClick={() => handleLoadToWorkbench(detailRecord.id)}>
              加载到工作台
            </Button>
          </>
        )}
      </Drawer>
    </PageShell>
  )
}

export default History
