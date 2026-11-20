import { useEffect, useState } from 'react'
import { Alert, Card, Collapse, Empty, Tag, Timeline } from 'antd'
import { BulbOutlined } from '@ant-design/icons'
import PageShell from '@/components/PageShell'
import TerminalCard from '@/components/TerminalCard'
import { getReflectionStatus } from '@/api/analysisApi'
import {
  loadLatestAnalysis,
  loadLatestCompletedReflection,
  updateStoredReflection,
} from '@/utils/analysisStorage'
import { describeReflectionLifecycle } from '@/utils/reflectionLifecycle'
import {
  normalizeReflectionPayload,
} from '@/utils/reflectionUtils'
import { DisplayParagraphs, DisplayStructuredBody } from '@/components/DisplayText'
import { cleanDisplayText } from '@/utils/displayTextUtils'

function ReflectionSection({ title, children, emptyText = '暂无数据' }) {
  if (!children || (Array.isArray(children) && !children.length)) {
    return (
      <Card size="small" title={title} className="reflection-section-card">
        <span className="reflection-empty-inline">{emptyText}</span>
      </Card>
    )
  }
  return (
    <Card size="small" title={title} className="reflection-section-card">
      {children}
    </Card>
  )
}

function Reflection() {
  const initial = loadLatestAnalysis()
  const [latest, setLatest] = useState(initial)
  const [lifecycle, setLifecycle] = useState(initial?.reflectionStatus ?? null)

  useEffect(() => {
    if (!initial?.taskId) return undefined
    let cancelled = false
    let timer
    const refresh = async () => {
      try {
        const status = await getReflectionStatus(initial.taskId)
        if (cancelled) return
        setLifecycle(status)
        if (status.reflection) {
          updateStoredReflection(initial.taskId, status.reflection, status)
          setLatest((current) => ({ ...current, reflection: status.reflection }))
        }
        if (status.status === 'pending' || status.status === 'running') {
          timer = setTimeout(refresh, 2000)
        }
      } catch (error) {
        if (!cancelled) setLifecycle({ status: 'failed', error: error.message })
      }
    }
    refresh()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [initial?.taskId])

  const historical = lifecycle?.status === 'not_applicable'
    ? loadLatestCompletedReflection()
    : null
  const displaySource = historical?.snapshot ?? latest
  const reflection = normalizeReflectionPayload(
    displaySource?.reflection ?? displaySource?.reflectionReport ?? {},
  )

  const hasContent = Boolean(
    reflection.summary ||
      reflection.metaReflection ||
      reflection.weightAdjustments?.length ||
      reflection.managerBlindSpots?.length ||
      reflection.riskControlImprovements?.length ||
      reflection.promptOptimizations?.length ||
      reflection.roleReflections?.length ||
      reflection.routerReflection ||
      reflection.weeklySummary,
  )

  const riskItems = reflection.riskControlImprovements ?? []

  if (!hasContent) {
    return (
      <PageShell
        title="反思记忆"
        subtitle="LLM 反思记忆库 · 最近一次分析"
        breadcrumbItems={[{ title: '工作台' }, { title: '反思记忆' }]}
      >
        <TerminalCard
          title="反思层：反思记忆库"
          subtitle="Reflection Memory"
          extra="Reflection Layer"
          icon={<BulbOutlined />}
          accent="cyan"
        >
          {lifecycle && (
            <Alert
              showIcon
              type={describeReflectionLifecycle(lifecycle).kind}
              message={describeReflectionLifecycle(lifecycle).message}
              description={lifecycle.error || lifecycle.reason}
              style={{ marginBottom: 16 }}
            />
          )}
          <Empty
            image={<BulbOutlined style={{ fontSize: 48, color: 'var(--text-muted)' }} />}
            description="暂无反思记忆，完成一次真实分析后将展示最近一次 reflection 内容。"
          />
        </TerminalCard>
      </PageShell>
    )
  }

  return (
    <PageShell
      title="反思记忆"
      subtitle="LLM 反思记忆库 · 最近一次分析"
      breadcrumbItems={[{ title: '工作台' }, { title: '反思记忆' }]}
      extra={<Tag className="tag-cyan">Latest</Tag>}
    >
      <TerminalCard
        title="反思层：反思记忆库"
        subtitle="Reflection Memory"
        extra="Latest Reflection"
        icon={<BulbOutlined />}
        accent="cyan"
      >
        {lifecycle && (
          <Alert
            showIcon
            type={describeReflectionLifecycle(lifecycle).kind}
            message={describeReflectionLifecycle(lifecycle).message}
            description={historical
              ? `当前展示 ${historical.stockCode} · ${historical.analysisDate} 的最近历史反思。`
              : lifecycle.error || lifecycle.reason}
            style={{ marginBottom: 16 }}
          />
        )}
        <Card size="small" className="reflection-summary-card" title="反思摘要">
          <DisplayParagraphs
            className="reflection-summary-text"
            children={reflection.fullText || reflection.summary || reflection.metaReflection || '暂无摘要'}
          />
        </Card>

        <Collapse
          ghost
          className="reflection-collapse"
          defaultActiveKey={['roles', 'weights', 'blindspots', 'risk', 'prompt', 'weekly']}
          items={[
            {
              key: 'roles',
              label: (
                <span>
                  角色完整反思{' '}
                  <Tag className="tag-neutral">{reflection.roleReflections?.length ?? 0}</Tag>
                </span>
              ),
              children: (
                <ReflectionSection title="经理、风控与最终决策者反思" emptyText="暂无角色反思">
                  {reflection.roleReflections?.map((item, i) => (
                    <Card key={`${item.role}-${i}`} size="small" title={item.role || `角色 ${i + 1}`}>
                      <DisplayParagraphs children={item.content} className="reflection-body-text" />
                    </Card>
                  ))}
                </ReflectionSection>
              ),
            },
            {
              key: 'weights',
              label: (
                <span>
                  权重调整 <Tag className="tag-neutral">{reflection.weightAdjustments?.length ?? 0}</Tag>
                </span>
              ),
              children: (
                <ReflectionSection title="权重调整建议" emptyText="暂无权重调整">
                  <>
                    {reflection.weightAdjustments?.length ? (
                      <Timeline
                        items={reflection.weightAdjustments.map((item, i) => ({
                          key: i,
                          color: 'cyan',
                          children: (
                            <div className="reflection-timeline-item">
                              <div className="reflection-item-head">
                                <Tag className="tag-neutral">{item.analystId}</Tag>
                                <span>
                                  {Math.round((item.currentWeight ?? 0) * 100)}% →{' '}
                                  {Math.round((item.suggestedWeight ?? 0) * 100)}%
                                </span>
                              </div>
                              <p>{cleanDisplayText(item.reason)}</p>
                            </div>
                          ),
                        }))}
                      />
                    ) : null}
                    {reflection.routerReflection ? (
                      <DisplayParagraphs
                        children={reflection.routerReflection}
                        className="reflection-body-text"
                      />
                    ) : null}
                  </>
                </ReflectionSection>
              ),
            },
            {
              key: 'blindspots',
              label: (
                <span>
                  经理盲区{' '}
                  <Tag className="tag-neutral">{reflection.managerBlindSpots?.length ?? 0}</Tag>
                </span>
              ),
              children: (
                <ReflectionSection title="经理决策盲区" emptyText="暂无盲区记录">
                  {reflection.managerBlindSpots?.length ? (
                    <Timeline
                      items={reflection.managerBlindSpots.map((item, i) => ({
                        key: i,
                        color: 'orange',
                        children: (
                          <div className="reflection-timeline-item">
                            <div className="reflection-item-head">
                              <Tag color="orange">{item.area}</Tag>
                            </div>
                            <p>{item.description}</p>
                            {item.suggestion && (
                              <p className="reflection-suggestion">建议：{item.suggestion}</p>
                            )}
                          </div>
                        ),
                      }))}
                    />
                  ) : null}
                </ReflectionSection>
              ),
            },
            {
              key: 'risk',
              label: (
                <span>
                  风控建议 <Tag className="tag-neutral">{riskItems.length}</Tag>
                </span>
              ),
              children: (
                <ReflectionSection title="风控改进建议" emptyText="暂无风控建议">
                  {riskItems.length ? (
                    <Timeline
                      items={riskItems.map((item, i) => ({
                        key: i,
                        color: 'red',
                        children: (
                          <div className="reflection-timeline-item">
                            <div className="reflection-item-head">
                              <Tag className="tag-neutral">
                                {cleanDisplayText(item.item) || `建议 ${i + 1}`}
                              </Tag>
                            </div>
                            <DisplayStructuredBody item={item} />
                          </div>
                        ),
                      }))}
                    />
                  ) : null}
                </ReflectionSection>
              ),
            },
            {
              key: 'prompt',
              label: (
                <span>
                  Prompt 优化{' '}
                  <Tag className="tag-neutral">{reflection.promptOptimizations?.length ?? 0}</Tag>
                </span>
              ),
              children: (
                <ReflectionSection title="Prompt 优化建议" emptyText="暂无 Prompt 优化建议">
                  {reflection.promptOptimizations?.length ? (
                    <Timeline
                      items={reflection.promptOptimizations.map((item, i) => ({
                        key: i,
                        color: 'blue',
                        children: (
                          <div className="reflection-timeline-item">
                            <div className="reflection-item-head">
                              <Tag className="tag-cyan">
                                {cleanDisplayText(item.target) || `Prompt ${i + 1}`}
                              </Tag>
                            </div>
                            <DisplayStructuredBody item={item} />
                          </div>
                        ),
                      }))}
                    />
                  ) : null}
                </ReflectionSection>
              ),
            },
            {
              key: 'weekly',
              label: <span>周度反思</span>,
              children: (
                <ReflectionSection title="周度策略备忘" emptyText="本次未触发周度反思">
                  {reflection.weeklySummary ? (
                    <DisplayParagraphs
                      children={reflection.weeklySummary}
                      className="reflection-body-text"
                    />
                  ) : null}
                </ReflectionSection>
              ),
            },
          ]}
        />
      </TerminalCard>
    </PageShell>
  )
}

export default Reflection
