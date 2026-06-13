import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Users, FileText, Send, MessageSquareReply, Loader2,
  Star, Mail, ChevronRight, Sparkles,
} from 'lucide-react'
import { getStats } from '../services/api'

interface Props {
  wsMessages: any[]
}

interface Stats {
  total_professors: number
  drafts_pending: number
  emails_sent: number
  total_drafts: number
  replies_received: number
  unread_replies: number
  positive_replies: number
  starred_without_draft: number
  profs_pending_email: number
}

const DEFAULT_STATS: Stats = {
  total_professors: 0, drafts_pending: 0, emails_sent: 0, total_drafts: 0,
  replies_received: 0, unread_replies: 0, positive_replies: 0,
  starred_without_draft: 0, profs_pending_email: 0,
}

export default function Dashboard({ wsMessages }: Props) {
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats>(DEFAULT_STATS)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getStats()
      .then((res) => setStats(res.data))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (wsMessages.length === 0) return
    const latest = wsMessages[wsMessages.length - 1]
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

  // ── Action items：「需要你的注意」──
  const actionItems = [
    {
      key: 'starred',
      icon: Star,
      iconClass: 'text-amber-500',
      count: stats.starred_without_draft,
      text: '位收藏导师还没生成草稿',
      cta: '去查看',
      onClick: () => navigate('/professors'),
    },
    {
      key: 'pending',
      icon: FileText,
      iconClass: 'text-indigo-500',
      count: stats.drafts_pending,
      text: '份草稿待你审核 / 发送',
      cta: '去审核',
      onClick: () => navigate('/drafts'),
    },
    {
      key: 'replies',
      icon: MessageSquareReply,
      iconClass: 'text-rose-500',
      count: stats.unread_replies,
      text: '封新回复未读',
      cta: '查看回复',
      onClick: () => navigate('/replies'),
    },
    {
      key: 'email',
      icon: Mail,
      iconClass: 'text-gray-500',
      count: stats.profs_pending_email,
      text: '位导师邮箱待补全（点击「一键补全」按钮）',
      cta: '去补全',
      onClick: () => navigate('/professors'),
    },
  ].filter((it) => it.count > 0)

  const allClear = !loading && actionItems.length === 0

  // ── 转化漏斗 ──
  const funnel = [
    { label: '导师', value: stats.total_professors, color: 'bg-blue-500', textColor: 'text-blue-700' },
    { label: '草稿', value: stats.total_drafts, color: 'bg-indigo-500', textColor: 'text-indigo-700' },
    { label: '已发', value: stats.emails_sent, color: 'bg-amber-500', textColor: 'text-amber-700' },
    { label: '回复', value: stats.replies_received, color: 'bg-purple-500', textColor: 'text-purple-700' },
    { label: '正面', value: stats.positive_replies, color: 'bg-green-500', textColor: 'text-green-700' },
  ]
  const funnelMax = Math.max(funnel[0].value, 1)
  const replyRate = stats.emails_sent > 0
    ? ((stats.replies_received / stats.emails_sent) * 100).toFixed(1)
    : '—'
  const positiveRate = stats.replies_received > 0
    ? ((stats.positive_replies / stats.replies_received) * 100).toFixed(1)
    : '—'

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

      {/* Action Items：需要你的注意 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="h-5 w-5 text-indigo-500" />
          <h3 className="text-lg font-semibold text-gray-800">需要你的注意</h3>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
          </div>
        ) : allClear ? (
          <div className="flex items-center gap-3 py-4 text-gray-500">
            <div className="rounded-full bg-green-50 p-2">
              <Sparkles className="h-5 w-5 text-green-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-700">一切顺利，没有待办</p>
              <p className="text-xs text-gray-400 mt-0.5">去导师列表里继续物色，或在回复跟踪等待回信。</p>
            </div>
          </div>
        ) : (
          <ul className="space-y-2">
            {actionItems.map(({ key, icon: Icon, iconClass, count, text, cta, onClick }) => (
              <li key={key}>
                <button
                  onClick={onClick}
                  className="w-full group flex items-center gap-3 rounded-lg border border-gray-100 px-4 py-3 hover:bg-gray-50 hover:border-indigo-200 transition-colors text-left"
                >
                  <Icon className={`h-5 w-5 shrink-0 ${iconClass}`} />
                  <p className="flex-1 text-sm text-gray-700">
                    <span className="font-semibold text-gray-900">{count}</span>
                    <span className="ml-1">{text}</span>
                  </p>
                  <span className="text-xs text-gray-400 group-hover:text-indigo-600 flex items-center gap-1 shrink-0">
                    {cta} <ChevronRight className="h-3.5 w-3.5" />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 转化漏斗 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">转化漏斗</h3>
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span>回复率 <span className="font-semibold text-gray-700">{replyRate}{replyRate !== '—' ? '%' : ''}</span></span>
            <span>正面率 <span className="font-semibold text-gray-700">{positiveRate}{positiveRate !== '—' ? '%' : ''}</span></span>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
          </div>
        ) : (
          <div className="space-y-2.5">
            {funnel.map(({ label, value, color, textColor }, i) => {
              const widthPct = (value / funnelMax) * 100
              const prevValue = i > 0 ? funnel[i - 1].value : value
              const dropPct = prevValue > 0 && i > 0 && prevValue !== value
                ? Math.round(((prevValue - value) / prevValue) * 100)
                : null
              return (
                <div key={label} className="flex items-center gap-3">
                  <div className="w-12 shrink-0 text-right text-sm font-medium text-gray-600">{label}</div>
                  <div className="flex-1 relative h-8 bg-gray-50 rounded-md overflow-hidden">
                    <div
                      className={`absolute inset-y-0 left-0 ${color} transition-all duration-500 flex items-center px-3`}
                      style={{ width: `${widthPct}%`, minWidth: value > 0 ? '2rem' : '0' }}
                    >
                      <span className="text-xs font-semibold text-white">{value}</span>
                    </div>
                  </div>
                  <div className="w-16 shrink-0 text-xs text-gray-400 text-right">
                    {dropPct !== null && <>−{dropPct}%</>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <p className="mt-3 text-xs text-gray-400">
          数字越往下漏越多说明该环节流失越大。回复率 ≈ 已发邮件被回复的比例；正面率 ≈ 回复里被你标为「正面」的比例。
        </p>
      </div>

    </div>
  )
}
