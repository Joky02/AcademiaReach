import { useState, useEffect } from 'react'
import { Users, FileText, Send, MessageSquareReply, Loader2 } from 'lucide-react'
import { getStats } from '../services/api'

interface Props {
  wsMessages: any[]
}

export default function Dashboard({ wsMessages }: Props) {
  const [stats, setStats] = useState({
    total_professors: 0,
    drafts_pending: 0,
    emails_sent: 0,
    replies_received: 0,
  })
  const [loading, setLoading] = useState(true)
  const [logs, setLogs] = useState<string[]>([])

  useEffect(() => {
    getStats()
      .then((res) => setStats(res.data))
      .finally(() => setLoading(false))
  }, [])

  // 监听 WebSocket 消息更新日志
  useEffect(() => {
    if (wsMessages.length === 0) return
    const latest = wsMessages[wsMessages.length - 1]
    if (latest.message) {
      setLogs((prev) => [...prev.slice(-49), `[${latest.channel || 'system'}] ${latest.message}`])
    }
    // 有新数据时刷新统计
    if (latest.type === 'done' || latest.type === 'professor' || latest.type === 'draft') {
      getStats().then((res) => setStats(res.data))
    }
  }, [wsMessages])

  const cards = [
    { label: '导师总数', value: stats.total_professors, icon: Users, color: 'bg-blue-500' },
    { label: '待发草稿', value: stats.drafts_pending, icon: FileText, color: 'bg-amber-500' },
    { label: '已发送', value: stats.emails_sent, icon: Send, color: 'bg-green-500' },
    { label: '已收回复', value: stats.replies_received, icon: MessageSquareReply, color: 'bg-purple-500' },
  ]

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">{label}</p>
                <p className="mt-1 text-3xl font-bold text-gray-900">
                  {loading ? <Loader2 className="h-8 w-8 animate-spin text-gray-300" /> : value}
                </p>
              </div>
              <div className={`rounded-lg ${color} p-3`}>
                <Icon className="h-6 w-6 text-white" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 实时日志 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <h3 className="mb-4 text-lg font-semibold text-gray-800">实时日志</h3>
        <div className="h-64 overflow-y-auto rounded-lg bg-gray-900 p-4 font-mono text-sm text-green-400">
          {logs.length === 0 ? (
            <p className="text-gray-500">暂无日志，启动搜索或生成邮件后将在此显示进度...</p>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="py-0.5">
                <span className="text-gray-500 mr-2">{String(i + 1).padStart(3, '0')}</span>
                {log}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
