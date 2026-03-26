import { useState, useEffect } from 'react'
import {
  MessageSquareReply, Loader2, RefreshCw, Mail, Eye, X,
} from 'lucide-react'
import { getReplies, checkReplies, markReplyRead } from '../services/api'

export default function Replies() {
  const [replies, setReplies] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [previewId, setPreviewId] = useState<number | null>(null)

  const fetchData = () => {
    getReplies()
      .then((res) => setReplies(res.data))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchData() }, [])

  const handleCheck = async () => {
    setChecking(true)
    try {
      await checkReplies()
      fetchData()
    } finally {
      setChecking(false)
    }
  }

  const handleMarkRead = async (id: number) => {
    await markReplyRead(id)
    fetchData()
  }

  const previewReply = replies.find((r) => r.id === previewId)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-bold text-gray-900">回复跟踪</h2>
        <button
          onClick={handleCheck}
          disabled={checking}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {checking ? '检查中...' : '检查回复'}
        </button>
      </div>

      {/* 预览模态 */}
      {previewReply && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">回复详情</h3>
              <button onClick={() => setPreviewId(null)}><X className="h-5 w-5 text-gray-400" /></button>
            </div>
            <div className="space-y-3">
              <p className="text-sm text-gray-500">
                来自: <span className="text-gray-900 font-medium">{previewReply.professor_name}</span>
                {' '}&lt;{previewReply.professor_email}&gt;
              </p>
              <p className="text-sm text-gray-500">主题: <span className="text-gray-900">{previewReply.subject}</span></p>
              <p className="text-sm text-gray-500">时间: {new Date(previewReply.received_at).toLocaleString('zh-CN')}</p>
              <hr />
              <div className="whitespace-pre-wrap text-sm text-gray-800 leading-relaxed">{previewReply.body}</div>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center p-12">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
        </div>
      ) : replies.length === 0 ? (
        <div className="rounded-xl bg-white p-12 text-center shadow-sm border border-gray-100">
          <MessageSquareReply className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-4 text-gray-500">暂无回复，点击"检查回复"手动触发检查</p>
        </div>
      ) : (
        <div className="space-y-4">
          {replies.map((r) => (
            <div
              key={r.id}
              className={`rounded-xl bg-white p-5 shadow-sm border transition-colors ${
                r.is_read ? 'border-gray-100' : 'border-indigo-200 bg-indigo-50/30'
              }`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {!r.is_read && (
                      <span className="h-2 w-2 rounded-full bg-indigo-500" />
                    )}
                    <span className="text-sm font-medium text-gray-900">
                      {r.professor_name}
                    </span>
                    <span className="text-xs text-gray-500">
                      @ {r.professor_university}
                    </span>
                  </div>
                  <h4 className="font-medium text-gray-800 truncate">{r.subject || '(无主题)'}</h4>
                  <p className="mt-1 text-sm text-gray-500 line-clamp-2">{r.body}</p>
                  <p className="mt-2 text-xs text-gray-400">
                    {new Date(r.received_at).toLocaleString('zh-CN')}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setPreviewId(r.id)
                      if (!r.is_read) handleMarkRead(r.id)
                    }}
                    className="rounded-lg border p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50"
                    title="查看详情"
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                  {!r.is_read && (
                    <button
                      onClick={() => handleMarkRead(r.id)}
                      className="rounded-lg border p-2 text-gray-400 hover:text-green-600 hover:bg-green-50"
                      title="标记已读"
                    >
                      <Mail className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
