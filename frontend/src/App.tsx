import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Search, FileText, Send, MessageSquareReply, Settings,
  GraduationCap, Menu, X,
} from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Professors from './pages/Professors'
import Drafts from './pages/Drafts'
import Sent from './pages/Sent'
import Replies from './pages/Replies'
import SettingsPage from './pages/Settings'
import SearchModal from './components/SearchModal'
import GlobalTaskIndicator from './components/GlobalTaskIndicator'
import { connectWebSocket, startSearch, stopSearch } from './services/api'

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/professors', label: '导师管理', icon: Search },
  { path: '/drafts', label: '邮件草稿', icon: FileText },
  { path: '/sent', label: '发送状态', icon: Send },
  { path: '/replies', label: '回复跟踪', icon: MessageSquareReply },
  { path: '/settings', label: '设置', icon: Settings },
]

export default function App() {
  const [wsMessages, setWsMessages] = useState<any[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // ── Global search state ──
  const [searching, setSearching] = useState(false)
  const [searchLog, setSearchLog] = useState<string[]>([])
  const [searchModalOpen, setSearchModalOpen] = useState(false)

  // ── Global compose state ──
  const [composing, setComposing] = useState(false)
  const [composeLog, setComposeLog] = useState<string[]>([])

  const handleWsMessage = useCallback((data: any) => {
    setWsMessages((prev) => [...prev.slice(-99), data])
  }, [])

  useEffect(() => {
    const ws = connectWebSocket(handleWsMessage)
    return () => ws.close()
  }, [handleWsMessage])

  // ── Route WebSocket messages to global search/compose state ──
  useEffect(() => {
    if (wsMessages.length === 0) return
    const latest = wsMessages[wsMessages.length - 1]

    if (latest.channel === 'search') {
      if (latest.type === 'progress' || latest.type === 'error') {
        setSearchLog((prev) => [...prev, latest.message])
      }
      if (latest.type === 'done' || latest.type === 'error') {
        setSearching(false)
      }
    }

    if (latest.channel === 'compose') {
      if (latest.type === 'progress' || latest.type === 'error') {
        setComposeLog((prev) => [...prev, latest.message])
      }
      if (latest.type === 'done' || latest.type === 'error') {
        setComposing(false)
      }
    }
  }, [wsMessages])

  // ── Global search actions ──
  const handleStartSearch = async () => {
    if (searching) {
      setSearchModalOpen(true)
      return
    }
    setSearching(true)
    setSearchLog([])
    setSearchModalOpen(true)
    try {
      await startSearch({ max_results: 20 })
    } catch {
      setSearching(false)
    }
  }

  const handleStopSearch = async () => {
    try { await stopSearch() } catch {}
    setSearching(false)
  }

  const handleStartCompose = () => {
    setComposing(true)
    setComposeLog([])
  }

  const handleStopCompose = () => {
    setComposing(false)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-40 w-64 transform bg-white shadow-xl transition-transform duration-200
          lg:static lg:translate-x-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        <div className="flex h-16 items-center gap-3 border-b px-6">
          <GraduationCap className="h-7 w-7 text-indigo-600" />
          <span className="text-lg font-bold text-gray-900">套磁 Agent</span>
        </div>
        <nav className="mt-4 space-y-1 px-3">
          {navItems.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              end={path === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-16 items-center gap-4 border-b bg-white px-4 lg:px-8">
          <button
            className="lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-6 w-6 text-gray-600" />
          </button>
          <h1 className="text-lg font-semibold text-gray-800">博士套磁助手</h1>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-8">
          <Routes>
            <Route path="/" element={<Dashboard wsMessages={wsMessages} />} />
            <Route
              path="/professors"
              element={
                <Professors
                  wsMessages={wsMessages}
                  searching={searching}
                  searchLog={searchLog}
                  onStartSearch={handleStartSearch}
                  onOpenSearchModal={() => setSearchModalOpen(true)}
                  composing={composing}
                  onStartCompose={handleStartCompose}
                />
              }
            />
            <Route path="/drafts" element={<Drafts />} />
            <Route path="/sent" element={<Sent />} />
            <Route path="/replies" element={<Replies />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>

      {/* Global search modal */}
      <SearchModal
        open={searchModalOpen}
        logs={searchLog}
        searching={searching}
        onClose={() => setSearchModalOpen(false)}
        onStop={handleStopSearch}
      />

      {/* Global floating task indicator */}
      <GlobalTaskIndicator
        searching={searching}
        searchLog={searchLog}
        composing={composing}
        composeLog={composeLog}
        onStopSearch={handleStopSearch}
        onStopCompose={handleStopCompose}
        onOpenSearchModal={() => setSearchModalOpen(true)}
      />
    </div>
  )
}
