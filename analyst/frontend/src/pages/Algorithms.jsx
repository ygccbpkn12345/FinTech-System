import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm,
  Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import PageShell from '@/components/PageShell'
import {
  createAlgorithm, deleteAlgorithm, fetchAlgorithms, fetchLocalTools, updateAlgorithm,
} from '@/api/algorithmApi'

const { Text } = Typography

const mappingRules = [{
  validator: (_, value) => {
    try {
      const data = JSON.parse(value || '{}')
      if (!data || Array.isArray(data) || typeof data !== 'object'
        || Object.values(data).some((item) => typeof item !== 'string' || !item.trim())) {
        throw new Error()
      }
      return Promise.resolve()
    } catch {
      return Promise.reject(new Error('请输入 JSON 对象，映射值须为非空字符串'))
    }
  },
}]

function Algorithms() {
  const [items, setItems] = useState([])
  const [localTools, setLocalTools] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState('')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [query, setQuery] = useState('')
  const [filterKind, setFilterKind] = useState('all')
  const [form] = Form.useForm()
  const kind = Form.useWatch('kind', form)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [algorithms, locals] = await Promise.all([fetchAlgorithms(), fetchLocalTools()])
      setItems(algorithms.items ?? [])
      setLocalTools(locals.items ?? [])
    } catch (error) {
      setLoadError(error.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const startEdit = (item = null) => {
    setEditing(item)
    form.resetFields()
    form.setFieldsValue({
      name: item?.name ?? '',
      description: item?.description ?? '',
      kind: item?.kind ?? 'http',
      required_parameters: item?.required_parameters ?? [],
      local_tool: item?.local_tool ?? undefined,
      url: item?.http?.url ?? '',
      method: item?.http?.method ?? 'POST',
      timeout_seconds: item?.http?.timeout_seconds ?? 10,
      request_mapping: JSON.stringify(item?.http?.request_mapping ?? {}, null, 2),
      response_mapping: JSON.stringify(item?.http?.response_mapping ?? {}, null, 2),
      summary_field: item?.http?.summary_field ?? '',
    })
    setOpen(true)
  }

  const save = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const body = {
      name: values.name,
      description: values.description.trim(),
      kind: values.kind,
      required_parameters: values.required_parameters ?? [],
      local_tool: values.kind === 'python' ? values.local_tool : null,
      http: values.kind === 'http' ? {
        url: values.url.trim(),
        method: values.method,
        timeout_seconds: values.timeout_seconds,
        request_mapping: JSON.parse(values.request_mapping || '{}'),
        response_mapping: JSON.parse(values.response_mapping || '{}'),
        summary_field: values.summary_field?.trim() || null,
      } : null,
    }
    setSaving(true)
    try {
      if (editing) await updateAlgorithm(editing.name, body)
      else await createAlgorithm(body)
      message.success(editing ? '算法已更新，下轮对话生效' : '算法已添加，可在对话中调用')
      setOpen(false)
      await load()
    } catch (error) {
      message.error(error.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (name) => {
    setDeleting(name)
    try {
      await deleteAlgorithm(name)
      message.success('算法已删除')
      await load()
    } catch (error) {
      message.error(error.message)
    } finally {
      setDeleting('')
    }
  }

  const columns = [
    { title: '算法名称', dataIndex: 'name', width: 200, render: (name) => <Text strong code>{name}</Text> },
    { title: '类型', dataIndex: 'kind', width: 100, render: (value) => <Tag color={value === 'http' ? 'blue' : 'green'}>{value === 'http' ? 'HTTP' : 'Python'}</Tag> },
    { title: '描述', dataIndex: 'description', width: 280 },
    { title: '必填参数', dataIndex: 'required_parameters', width: 220, render: (parameters) => parameters.length ? <Space wrap size={[0, 4]}>{parameters.map((p) => <Tag key={p}>{p}</Tag>)}</Space> : <Text type="secondary">无</Text> },
    { title: '执行目标', key: 'target', width: 250, render: (_, item) => <Text style={{ wordBreak: 'break-all' }}>{item.kind === 'python' ? item.local_tool : `${item.http.method} ${item.http.url}`}</Text> },
    { title: '操作', key: 'actions', fixed: 'right', width: 140, render: (_, item) => (
      <Space>
        <Button type="link" size="small" onClick={() => startEdit(item)}>编辑</Button>
        <Popconfirm title={`删除算法 ${item.name}？`} description="后续对话将无法调用此算法，正在执行的任务继续完成。" onConfirm={() => remove(item.name)} okText="删除" cancelText="取消">
          <Button type="link" danger size="small" loading={deleting === item.name}>删除</Button>
        </Popconfirm>
      </Space>
    ) },
  ]

  const filtered = items.filter((item) => (
    (filterKind === 'all' || item.kind === filterKind)
    && `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase().trim())
  ))

  return (
    <PageShell title="算法管理" subtitle="注册算法 · 统一发现 · 对话调用" breadcrumbItems={[{ title: '工作台' }, { title: '算法管理' }]}
      extra={<Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => startEdit()}>添加算法</Button></Space>}
    >
      <Space direction="vertical" size={20} style={{ width: '100%' }}>
        <Alert type="info" showIcon message="注册后即可通过对话调用" description="描述用于帮助助手选择算法，请写清适用问题。配置保存后即时生效，重启后保留。" />
        {loadError && <Alert type="error" showIcon message="读取算法失败" description={loadError} action={<Button onClick={load}>重试</Button>} />}
        <Card>
          <Space wrap style={{ marginBottom: 20 }}>
            <Input prefix={<SearchOutlined />} aria-label="搜索算法" placeholder="搜索算法名称或描述" value={query} onChange={(event) => setQuery(event.target.value)} allowClear style={{ width: 280 }} />
            <Select aria-label="算法类型筛选" value={filterKind} onChange={setFilterKind} style={{ width: 150 }} options={[{ value: 'all', label: '全部类型' }, { value: 'python', label: 'Python' }, { value: 'http', label: 'HTTP' }]} />
            <Text type="secondary">共 {filtered.length} 个算法</Text>
          </Space>
          <Table rowKey="name" columns={columns} dataSource={filtered} loading={loading} scroll={{ x: 1120 }} pagination={{ pageSize: 10, hideOnSinglePage: true }} locale={{ emptyText: query || filterKind !== 'all' ? '没有匹配的算法' : '暂无算法，点击“添加算法”开始注册' }} />
        </Card>
      </Space>

      <Modal title={editing ? `编辑算法 · ${editing.name}` : '添加算法'} open={open} onCancel={() => { if (!saving) setOpen(false) }} onOk={save} confirmLoading={saving} cancelButtonProps={{ disabled: saving }} okText="保存算法" cancelText="取消" width={680} forceRender>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="算法名称" extra="唯一标识，创建后不可修改" rules={[{ required: true, message: '请输入算法名称' }, { pattern: /^[A-Za-z][A-Za-z0-9_-]{0,63}$/, message: '以字母开头，支持字母、数字、下划线和短横线，最长 64 字符' }]}>
            <Input disabled={Boolean(editing)} placeholder="例如 sentiment_analysis" />
          </Form.Item>
          <Form.Item name="description" label="算法描述" rules={[{ required: true, whitespace: true, message: '请描述算法用途和适用场景' }]}>
            <Input.TextArea rows={3} maxLength={2000} showCount placeholder="例如：分析一段财经新闻的情绪，返回正面、负面或中性及评分" />
          </Form.Item>
          <Form.Item name="kind" label="算法类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'http', label: 'HTTP 服务' }, { value: 'python', label: '本地 Python' }]} />
          </Form.Item>
          {kind === 'python' && <Form.Item name="local_tool" label="本地算法" extra="选择服务端已安装的算法实现" rules={[{ required: true, message: '请选择本地算法' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择本地算法" options={localTools.map((tool) => ({ value: tool.name, label: `${tool.name} · ${tool.description}` }))} onChange={(value) => {
              const selected = localTools.find((tool) => tool.name === value)
              if (selected) form.setFieldsValue({ required_parameters: selected.required_parameters })
            }} />
          </Form.Item>}
          <Form.Item name="required_parameters" label="必填参数" extra="逐个输入参数名并回车；调用时缺少参数，助手会追问。" rules={[{ validator: (_, value = []) => value.some((p) => !/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(p)) ? Promise.reject(new Error('参数名仅支持字母、数字和下划线，且不能以数字开头')) : Promise.resolve() }]}>
            <Select mode="tags" tokenSeparators={[',', '，']} placeholder="例如 query、stockCode" />
          </Form.Item>
          {kind === 'http' && <>
            <Form.Item name="url" label="服务地址" extra="调用时始终使用此固定地址" rules={[{ required: true, message: '请输入服务地址' }, { type: 'url', message: '请输入有效的 HTTP/HTTPS 地址' }, { pattern: /^https?:\/\//, message: '仅支持 HTTP/HTTPS 地址' }]}><Input placeholder="https://your-service.example/analyze" /></Form.Item>
            <Space align="start" size={24} wrap>
              <Form.Item name="method" label="请求方法" rules={[{ required: true }]}><Select style={{ width: 140 }} options={[{ value: 'POST', label: 'POST · JSON' }, { value: 'GET', label: 'GET · 查询参数' }]} /></Form.Item>
              <Form.Item name="timeout_seconds" label="超时（秒）" rules={[{ required: true }]}><InputNumber min={0.1} max={300} style={{ width: 140 }} /></Form.Item>
            </Space>
            <Form.Item name="request_mapping" label="请求字段映射（JSON）" extra={'例如 {"query":"text"}；也可在此声明可选参数'} rules={mappingRules}><Input.TextArea rows={3} spellCheck={false} /></Form.Item>
            <Form.Item name="response_mapping" label="响应字段映射（JSON）" extra={'例如 {"score":"data.score"}；留空对象则返回完整响应'} rules={mappingRules}><Input.TextArea rows={3} spellCheck={false} /></Form.Item>
            <Form.Item name="summary_field" label="结果摘要字段" extra="从映射后的结果读取，支持 data.message 形式的路径"><Input placeholder="例如 summary" /></Form.Item>
          </>}
        </Form>
      </Modal>
    </PageShell>
  )
}

export default Algorithms
