import { Steps } from 'antd'

import {

  CloudDownloadOutlined,

  TeamOutlined,

  NodeIndexOutlined,

  ApartmentOutlined,

  SafetyCertificateOutlined,

  CheckCircleOutlined,

  BulbOutlined,

} from '@ant-design/icons'

import TerminalCard from './TerminalCard'

import {

  buildStepStatuses,

  normalizeDisplayProgress,

  resolveActiveStepIndex,

  FLOW_STEPS,

} from '@/utils/processStepUtils'



const STEP_ICONS = [

  <CloudDownloadOutlined />,

  <TeamOutlined />,

  <NodeIndexOutlined />,

  <ApartmentOutlined />,

  <SafetyCertificateOutlined />,

  <CheckCircleOutlined />,

  <BulbOutlined />,

]



function ProcessSteps({

  currentStep = 0,

  status = 'process',

  currentNode = '',

  progress = 0,

  taskStatus = 'running',

  compact = false,

}) {

  const overallStatus =

    status === 'finish' ? 'finish' : status === 'error' ? 'error' : 'process'



  const isCompleted = taskStatus === 'completed' || status === 'finish'

  const runtimeStatus = isCompleted ? 'completed' : 'running'

  const cappedProgress = normalizeDisplayProgress({ progress, status: runtimeStatus })



  const activeIndex = resolveActiveStepIndex({

    currentNode,

    progress: cappedProgress,

    status: runtimeStatus,

    currentStep,

  })



  const stepItems = buildStepStatuses(activeIndex, overallStatus)

  const stepNum = isCompleted

    ? FLOW_STEPS.length

    : Math.min(activeIndex + 1, FLOW_STEPS.length)



  return (

    <TerminalCard

      title="编排层：Multi-Agent 流程"

      subtitle="Orchestration Layer"

      extra={`Step ${stepNum}/${FLOW_STEPS.length}`}

      icon={<NodeIndexOutlined />}

      accent="blue"

      className={compact ? 'process-steps-card--compact' : ''}

    >

      <Steps

        size="small"

        items={stepItems.map((item, index) => ({

          title: <span className="step-title">{item.title}</span>,

          icon: STEP_ICONS[index],

          status: item.status,

        }))}

        className="process-steps"

      />

    </TerminalCard>

  )

}



export default ProcessSteps

