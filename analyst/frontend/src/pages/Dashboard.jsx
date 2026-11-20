import { useCallback, useEffect, useRef, useState } from 'react'

import { Col, message, Row } from 'antd'

import dayjs from 'dayjs'
import { useLocation, useNavigate } from 'react-router-dom'

import {
  BACKEND_UNAVAILABLE_MSG,
  DEFAULT_POLL_INTERVAL_MS,
  getAnalysisResult,
  normalizeStockCodeInput,
  runAnalysisWorkflow,
  USE_MOCK,
} from '@/api/analysisApi'

import { checkStockAnalyzable, fetchSymbolAvailableDates, loadAvailableSymbols } from '@/api/configApi'
import { checkAnalysisDateAvailability } from '@/utils/analysisDateGuard'
import { resolveChatHandoff } from '@/utils/chatDashboardHandoff'

import {

  consumePendingLoad,

  saveAnalysisToHistory,

} from '@/utils/analysisStorage'

import ErrorBoundary from '@/components/ErrorBoundary'

import StockInputBar from '@/components/StockInputBar'

import MarketOverview from '@/components/MarketOverview'

import MarketChartPanel from '@/components/MarketChartPanel'

import ProcessSteps from '@/components/ProcessSteps'

import AnalystPanel from '@/components/AnalystPanel'

import RouterWeightPanel from '@/components/RouterWeightPanel'

import AnalysisWorkbenchTabs from '@/components/AnalysisWorkbenchTabs'

import DecisionCockpit from '@/components/DecisionCockpit'

import DecisionCockpitLoading from '@/components/DecisionCockpitLoading'

import AnalysisLoadingPanels from '@/components/AnalysisLoadingPanels'
import DashboardWelcome from '@/components/DashboardWelcome'



const UNSUPPORTED_STOCK_MSG = '当前股票数据不完整，请先在系统配置页上传数据。'



function Dashboard() {

  const location = useLocation()
  const navigate = useNavigate()
  const loadedReport = useRef(null)
  const reportTask = new URLSearchParams(location.search).get('task')

  const [stockCode, setStockCode] = useState('000063')

  const [analysisDate, setAnalysisDate] = useState(dayjs('2024-01-03'))

  const [loading, setLoading] = useState(false)

  const [hasStarted, setHasStarted] = useState(false)

  const [analyzed, setAnalyzed] = useState(false)

  const [currentStep, setCurrentStep] = useState(0)

  const [stepStatus, setStepStatus] = useState('process')

  const [taskStatus, setTaskStatus] = useState('idle')

  const [analysisData, setAnalysisData] = useState(null)

  const [taskId, setTaskId] = useState(null)

  const [error, setError] = useState(null)

  const [progress, setProgress] = useState(0)

  const [currentNode, setCurrentNode] = useState('')

  const [moduleEvents, setModuleEvents] = useState({})

  const [streamState, setStreamState] = useState('idle')

  const [dataStatus, setDataStatus] = useState(null)
  const [dataStatusLoading, setDataStatusLoading] = useState(false)
  const [quickPickCodes, setQuickPickCodes] = useState(['000063', '000157', '000333', '000921', '000988'])

  const abortRef = useRef(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    const fetched = location.state
    if (!fetched?.dataFetched) return
    if (fetched.stockCode) setStockCode(fetched.stockCode)
    if (fetched.analysisDate) setAnalysisDate(dayjs(fetched.analysisDate))
    if (fetched.dataStatus) setDataStatus(fetched.dataStatus)
    setError(null)
    message.success(
      `${fetched.stockCode || '股票'} 数据已更新至 ${fetched.analysisDate || '最新交易日'}`,
    )
  }, [location.key, location.state])



  // 从聊天结果卡进入或刷新报告时恢复已有任务

  useEffect(() => {

    const handoff = resolveChatHandoff(location.state)
    const reportId = handoff?.taskId ?? reportTask
    if (!reportId || loadedReport.current === reportId) return undefined

    let cancelled = false

    setLoading(true)

    setHasStarted(true)

    setAnalyzed(false)

    setError(null)

    setTaskStatus('running')

    setTaskId(reportId)

    getAnalysisResult(encodeURIComponent(reportId))

      .then((result) => {

        if (cancelled) return

        loadedReport.current = reportId
        if (handoff && reportTask !== reportId) {
          setLoading(false)
          navigate({ search: '?task=' + encodeURIComponent(reportId) }, { replace: true })
        }
        setAnalysisData(result)

        setAnalyzed(true)

        setTaskStatus('completed')

        setProgress(100)

        setCurrentNode('completed')

        setStepStatus('finish')

        if (result?.stock?.code) setStockCode(result.stock.code)

        if (result?.stock?.analysisDate && result.stock.analysisDate !== '--') {

          setAnalysisDate(dayjs(result.stock.analysisDate))

        }

      })

      .catch((err) => {

        if (cancelled) return

        setAnalysisData(null)

        setAnalyzed(false)

        setHasStarted(false)

        setTaskStatus('failed')

        setError(err?.message || '加载个股分析结果失败，请重新发起分析')

      })

      .finally(() => {

        if (!cancelled) setLoading(false)

      })

    return () => {

      cancelled = true

    }

  }, [location.state, navigate, reportTask])



  useEffect(() => {

    const pending = consumePendingLoad()

    if (!pending?.snapshot) return



    const snapshot = pending.snapshot
    const savedTaskId = snapshot.taskId ?? null
    loadedReport.current = savedTaskId
    setTaskId(savedTaskId)
    if (savedTaskId && !USE_MOCK) {
      navigate({ search: '?task=' + encodeURIComponent(savedTaskId) }, { replace: true })
    }

    setAnalysisData(snapshot)

    setHasStarted(true)

    setAnalyzed(true)

    setStepStatus('finish')

    setTaskStatus('completed')

    setStockCode(pending.stockCode ?? snapshot.stock?.code ?? '000063')

    if (pending.analysisDate) {

      setAnalysisDate(dayjs(pending.analysisDate))

    } else if (snapshot.stock?.analysisDate) {

      setAnalysisDate(dayjs(snapshot.stock.analysisDate))

    }

    setProgress(100)

    setCurrentNode('completed')

  }, [])



  useEffect(() => {
    loadAvailableSymbols()
      .then((list) => {
        const codes = list.map((item) => item.symbol).filter(Boolean)
        if (codes.length) setQuickPickCodes(codes)
      })
      .catch(() => {
        /* keep fallback list */
      })
  }, [])



  const handleCheckDataStatus = useCallback(async () => {
    const code = normalizeStockCodeInput(stockCode)
    if (!code) {
      setDataStatus(null)
      return
    }
    setDataStatusLoading(true)
    try {
      const status = await checkStockAnalyzable(code)
      setDataStatus(status)
    } catch (err) {
      message.error(err.message || '查询数据状态失败')
    } finally {
      setDataStatusLoading(false)
    }
  }, [stockCode])



  useEffect(() => {
    const code = normalizeStockCodeInput(stockCode)
    if (!code || code.length < 6) {
      setDataStatus(null)
      return
    }
    const timer = setTimeout(() => {
      checkStockAnalyzable(code).then(setDataStatus).catch(() => {})
    }, 500)
    return () => clearTimeout(timer)
  }, [stockCode])



  const handleAnalyze = useCallback(async () => {

    if (!stockCode.trim() || loading) return



    const requestCode = normalizeStockCodeInput(stockCode)

    let status = dataStatus
    if (!status || status.symbol !== requestCode) {
      status = await checkStockAnalyzable(requestCode)
      setDataStatus(status)
    }

    if (!status.available) {
      message.warning(UNSUPPORTED_STOCK_MSG, 6)
      return
    }

    const selectedDate = analysisDate.format('YYYY-MM-DD')
    try {
      const availableDates = await fetchSymbolAvailableDates(requestCode)
      const dateCheck = checkAnalysisDateAvailability(selectedDate, availableDates)
      if (!dateCheck.allowed) {
        message.warning(dateCheck.message, 6)
        return
      }
    } catch (err) {
      message.warning(err.message || '无法确认分析日期是否可用，请稍后重试', 6)
      return
    }



    abortRef.current?.abort()

    const controller = new AbortController()

    abortRef.current = controller



    setLoading(true)

    setError(null)

    setHasStarted(true)

    setAnalyzed(false)

    setCurrentStep(0)

    setStepStatus('process')

    setTaskStatus('running')

    setTaskId(null)

    setAnalysisData(null)

    setProgress(0)

    setCurrentNode('')

    setModuleEvents({})

    setStreamState('connecting')



    try {

      const { taskId: newTaskId, result } = await runAnalysisWorkflow(

        {

          stockCode: requestCode,

          analysisDate: analysisDate.format('YYYY-MM-DD'),

        },

        {

          signal: controller.signal,

          interval: DEFAULT_POLL_INTERVAL_MS,

          onStatus: (status) => {

            setTaskId(status.taskId)

            setCurrentStep(status.currentStep ?? 0)

            setProgress(status.progress ?? 0)

            setCurrentNode(status.currentNode ?? status.message ?? '')

            setTaskStatus(status.status ?? 'running')

            setStepStatus(

              status.status === 'completed'

                ? 'finish'

                : status.status === 'failed' || status.error === true

                  ? 'error'

                  : 'process',

            )

          },

          onResult: (result) => {

            setAnalysisData(result)

          },

          onModuleEvent: (event) => {

            setModuleEvents((current) => {
              const previous = current[event.module]
              if (previous && previous.id >= event.id) return current
              return { ...current, [event.module]: event }
            })

          },

          onStreamState: setStreamState,

        },

      )



      loadedReport.current = newTaskId
      setTaskId(newTaskId)
      if (newTaskId && !USE_MOCK) {
        navigate({ search: '?task=' + encodeURIComponent(newTaskId) }, { replace: true })
      }

      setAnalysisData(result)

      setStepStatus('finish')

      setTaskStatus('completed')

      setAnalyzed(true)

      setProgress(100)

      setCurrentNode('completed')



      saveAnalysisToHistory({ ...result, taskId: newTaskId }, {

        stockCode: requestCode,

        analysisDate: analysisDate.format('YYYY-MM-DD'),

        source: USE_MOCK || result.analysisMode === 'mock' ? 'mock' : 'real_model',

      })

    } catch (err) {

      if (err.message !== '分析已取消') {

        const errMsg = err.message || BACKEND_UNAVAILABLE_MSG

        setError(errMsg)

        message.error(errMsg, 8)

        setStepStatus('error')

        setTaskStatus('failed')

        setAnalysisData(null)

      }

    } finally {

      setLoading(false)

    }

  }, [stockCode, analysisDate, loading, dataStatus, navigate])



  const stock = analysisData?.stock ?? analysisData?.stockInfo ?? {}

  const chartData = analysisData?.chartData ?? analysisData?.marketChart

  const isUp = (typeof stock.change === 'number' ? stock.change : 0) >= 0

  const routerWeights = analysisData?.routerWeights ?? analysisData?.routingWeights ?? []

  const managerTree = analysisData?.managerDecision?.tree ?? analysisData?.managerDecisionTree ?? []

  const managerPreReflection =

    analysisData?.managerDecision?.preReflection ?? analysisData?.managerPreReflection ?? {}


  const riskList = analysisData?.riskList ?? analysisData?.riskAssessment?.items ?? []

  const finalDecision = analysisData?.finalDecision ?? {}



  return (

    <div className="dashboard-workbench">

      <StockInputBar

        stockCode={stockCode}

        onStockCodeChange={setStockCode}

        analysisDate={analysisDate}

        onDateChange={setAnalysisDate}

        onAnalyze={handleAnalyze}

        loading={loading}

        analyzed={analyzed}

        error={error}

        currentNode={currentNode}

        progress={progress}

        taskStatus={taskStatus}

        onCloseError={() => setError(null)}

        quickPickCodes={quickPickCodes}

        dataStatus={dataStatus}

        dataStatusLoading={dataStatusLoading}

        onCheckDataStatus={handleCheckDataStatus}

      />



      {!hasStarted && !loading && <DashboardWelcome />}



      {hasStarted && (

        <ErrorBoundary>

          <Row gutter={[12, 0]} className="dashboard-split-row">

            <Col xs={24} lg={17} xl={17} className="dashboard-main-col">

              <div className="dashboard-stack dashboard-stack--compact">

                <ProcessSteps

                  currentStep={currentStep}

                  status={stepStatus}

                  currentNode={currentNode}

                  progress={progress}

                  taskStatus={taskStatus}

                  compact

                />



                {hasStarted && !analysisData && (
                  <AnalysisLoadingPanels
                    modules={moduleEvents}
                    currentNode={currentNode}
                    taskStatus={taskStatus}
                    streamState={streamState}
                  />
                )}



                {analysisData && (

                  <>

                    <MarketOverview stock={stock} compact />

                    <MarketChartPanel chartData={chartData} isUp={isUp} />

                    <AnalystPanel

                      analysts={analysisData.analysts ?? []}

                      routerWeights={routerWeights}

                    />

                    {analyzed && (

                      <>

                        <RouterWeightPanel routerWeights={routerWeights} />

                        <AnalysisWorkbenchTabs

                          decisionTree={managerTree}

                          preReflection={managerPreReflection}

                          riskAssessment={riskList}
                    taskId={USE_MOCK ? null : taskId}


                        />

                      </>

                    )}

                  </>

                )}

              </div>

            </Col>



            <Col xs={24} lg={7} xl={7} className="dashboard-cockpit-col">

              <div className="decision-cockpit-sticky">

                {analyzed && analysisData ? (
                  <DecisionCockpit
                    decision={finalDecision}
                    riskAssessment={riskList}
                    taskId={USE_MOCK ? null : taskId}
                  />
                ) : (
                  <DecisionCockpitLoading
                    loading={loading}
                    failed={taskStatus === 'failed' || Boolean(error)}
                    error={error}
                  />
                )}

              </div>

            </Col>

          </Row>

        </ErrorBoundary>

      )}

    </div>

  )

}



export default Dashboard
