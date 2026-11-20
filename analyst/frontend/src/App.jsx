import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ErrorBoundary from './components/ErrorBoundary'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import History from './pages/History'
import Reflection from './pages/Reflection'
import Settings from './pages/Settings'
import Algorithms from './pages/Algorithms'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/chat"
          element={
            <ErrorBoundary>
              <Chat />
            </ErrorBoundary>
          }
        />
        <Route path="/" element={<AppLayout />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route
            path="dashboard"
            element={
              <ErrorBoundary>
                <Dashboard />
              </ErrorBoundary>
            }
          />
          <Route path="history" element={<History />} />
          <Route path="reflection" element={
            <ErrorBoundary>
              <Reflection />
            </ErrorBoundary>
          } />
          <Route path="settings" element={<Settings />} />
          <Route path="algorithms" element={<Algorithms />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
