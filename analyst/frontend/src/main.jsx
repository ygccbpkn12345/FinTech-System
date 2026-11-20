import { StrictMode } from 'react'
import '@ant-design/v5-patch-for-react-19'
import { createRoot } from 'react-dom/client'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/global.css'

/** 同花顺浅色风：白底 + 品牌红顶栏 */
const THS = {
  brand: '#e93030',
  brandDark: '#c8161d',
  brandLight: '#e93030',
  bgBase: '#eef0f3',
  bgContainer: '#ffffff',
  bgElevated: '#ffffff',
  bgSidebar: '#ffffff',
  header: '#e93030',
  border: '#e4e7ed',
  text: '#333333',
  textSecondary: '#666666',
  textMuted: '#999999',
  up: '#f5222d',
  down: '#00b578',
  warning: '#faad14',
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: THS.brand,
          colorSuccess: THS.down,
          colorError: THS.up,
          colorWarning: THS.warning,
          colorInfo: THS.brand,
          colorBgBase: THS.bgBase,
          colorBgContainer: THS.bgContainer,
          colorBgElevated: THS.bgElevated,
          colorBgLayout: THS.bgBase,
          colorBorder: THS.border,
          colorBorderSecondary: '#f0f0f0',
          colorText: THS.text,
          colorTextSecondary: THS.textSecondary,
          colorTextDescription: THS.textMuted,
          borderRadius: 6,
          borderRadiusLG: 8,
          fontSize: 13,
          wireframe: false,
        },
        components: {
          Layout: {
            bodyBg: THS.bgBase,
            siderBg: THS.bgSidebar,
            headerBg: THS.header,
            headerColor: '#ffffff',
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: 'rgba(233, 48, 48, 0.08)',
            itemSelectedColor: THS.brand,
            itemHoverBg: 'rgba(233, 48, 48, 0.04)',
            itemColor: THS.textSecondary,
          },
          Card: {
            colorBgContainer: '#ffffff',
            colorBorderSecondary: THS.border,
          },
          Table: {
            headerBg: '#fafafa',
            headerColor: THS.textSecondary,
            borderColor: THS.border,
            // 固定列必须使用不透明背景，防止横向滚动时透出下方单元格的文字。
            rowHoverBg: '#fef7f7',
          },
          Tabs: {
            inkBarColor: THS.brand,
            itemActiveColor: THS.brand,
            itemHoverColor: THS.brandDark,
          },
          Segmented: {
            itemSelectedBg: '#ffffff',
            itemSelectedColor: THS.brand,
            trackBg: '#f5f5f5',
          },
          Steps: {
            colorText: THS.textSecondary,
            colorPrimary: THS.brand,
          },
          Button: {
            primaryShadow: '0 2px 6px rgba(233, 48, 48, 0.25)',
          },
          Alert: {
            colorInfoBg: '#fff1f0',
            colorInfoBorder: '#ffccc7',
          },
          Progress: {
            defaultColor: THS.brand,
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </StrictMode>,
)
