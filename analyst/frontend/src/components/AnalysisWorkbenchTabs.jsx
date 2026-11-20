import { Tabs } from 'antd'

import {

  ApartmentOutlined,

  EyeOutlined,

  SafetyCertificateOutlined,

} from '@ant-design/icons'

import TerminalCard from './TerminalCard'

import ManagerDecisionTree from './ManagerDecisionTree'

import ManagerPreReflection from './ManagerPreReflection'

import RiskPanel from './RiskPanel'



function AnalysisWorkbenchTabs({

  decisionTree,

  preReflection,

  riskAssessment,

}) {

  const items = [

    {

      key: 'tree',

      label: (

        <span>

          <ApartmentOutlined /> 经理树状推演

        </span>

      ),

      forceRender: true,

      children: <ManagerDecisionTree decisionTree={decisionTree} />,

    },

    {

      key: 'prereflect',

      label: (

        <span>

          <EyeOutlined /> 经理事前反思

        </span>

      ),

      forceRender: true,

      children: <ManagerPreReflection preReflection={preReflection} />,

    },

    {

      key: 'risk',

      label: (

        <span>

          <SafetyCertificateOutlined /> 风险管理评估

        </span>

      ),

      forceRender: true,

      children: <RiskPanel riskAssessment={riskAssessment} bare />,

    },

  ]



  return (

    <TerminalCard

      title="决策层：经理树状推演"

      subtitle="Decision Layer"

      extra="Workbench"

      icon={<ApartmentOutlined />}

      accent="blue"

      className="workbench-terminal-card"

      bodyClassName="workbench-tabs-body"

    >

      <Tabs

        items={items}

        className="workbench-tabs"

        defaultActiveKey="tree"

        destroyOnHidden={false}

      />

    </TerminalCard>

  )

}



export default AnalysisWorkbenchTabs

