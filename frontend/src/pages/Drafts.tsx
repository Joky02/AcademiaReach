import { useState, useEffect } from 'react'
import {
  FileText, Send, Edit3, SkipForward, Loader2, Sparkles, Eye, X, Trash2,
} from 'lucide-react'
import { getDrafts, updateDraft, sendEmail, startCompose, deleteDraft } from '../services/api'

export default function Drafts() {
  const [drafts, setDrafts] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [composing, setComposing] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState({ subject: '', body: '' })
  const [previewId, setPreviewId] = useState<number | null>(null)
  const [filter, setFilter] = useState<string>('')

  const fetchData = () => {
    getDrafts(filter || undefined)
      .then((res) => setDrafts(res.data))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchData() }, [filter])

  const handleCompose = async () => {
    setComposing(true)
    try {
      await startCompose()
      // 等一会再刷新
      setTimeout(fetchData, 3000)
    } finally {
      setTimeout(() => setComposing(false), 5000)
    }
  }

  const handleSend = async (id: number) => {
    try {
      await sendEmail(id)
      fetchData()
    } catch (e: any) {
      alert(e.response?.data?.detail || '发送失败')
    }
  }

  const handleSkip = async (id: number) => {
    await updateDraft(id, { status: 'skipped' })
    fetchData()
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除这条草稿吗？')) return
    await deleteDraft(id)
    fetchData()
  }

  const startEdit = (draft: any) => {
    setEditingId(draft.id)
    setEditForm({ subject: draft.subject, body: draft.body })
  }

  const saveEdit = async () => {
    if (editingId === null) return
    await updateDraft(editingId, editForm)
    setEditingId(null)
    fetchData()
  }

  const previewDraft = drafts.find((d) => d.id === previewId)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-bold text-gray-900">邮件草稿</h2>
        <div className="flex gap-3">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="">全部</option>
            <option value="pending">待发送</option>
            <option value="sent">已发送</option>
            <option value="skipped">已跳过</option>
          </select>
          <button
            onClick={handleCompose}
            disabled={composing}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {composing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {composing ? '生成中...' : '生成草稿'}
          </button>
        </div>
      </div>

      {/* 编辑模态 */}
      {editingId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">编辑草稿</h3>
              <button onClick={() => setEditingId(null)}><X className="h-5 w-5 text-gray-400" /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">主题</label>
                <input
                  value={editForm.subject}
                  onChange={(e) => setEditForm({ ...editForm, subject: e.target.value })}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">正文</label>
                <textarea
                  value={editForm.body}
                  onChange={(e) => setEditForm({ ...editForm, body: e.target.value })}
                  rows={12}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-3">
              <button onClick={() => setEditingId(null)} className="rounded-lg border px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">取消</button>
              <button onClick={saveEdit} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">保存</button>
            </div>
          </div>
        </div>
      )}

      {/* 预览模态 */}
      {previewDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">邮件预览</h3>
              <button onClick={() => setPreviewId(null)}><X className="h-5 w-5 text-gray-400" /></button>
            </div>
            <div className="space-y-3">
              <p className="text-sm text-gray-500">收件人: <span className="text-gray-900">{previewDraft.professor_name} &lt;{previewDraft.professor_email}&gt;</span></p>
              <p className="text-sm text-gray-500">主题: <span className="font-medium text-gray-900">{previewDraft.subject}</span></p>
              <hr />
              <div className="whitespace-pre-wrap text-sm text-gray-800 leading-relaxed">{previewDraft.body}</div>
            </div>
          </div>
        </div>
      )}

      {/* 草稿列表 */}
      <div className="space-y-4">
        {loading ? (
          <div className="flex items-center justify-center p-12">
            <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
          </div>
        ) : drafts.length === 0 ? (
          <div className="rounded-xl bg-white p-12 text-center shadow-sm border border-gray-100">
            <FileText className="mx-auto h-12 w-12 text-gray-300" />
            <p className="mt-4 text-gray-500">暂无草稿，点击"生成草稿"按钮开始</p>
          </div>
        ) : (
          drafts.map((d) => (
            <div key={d.id} className="rounded-xl bg-white p-5 shadow-sm border border-gray-100">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      d.status === 'pending' ? 'bg-amber-100 text-amber-700' :
                      d.status === 'sent' ? 'bg-green-100 text-green-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>
                      {d.status === 'pending' ? '待发送' : d.status === 'sent' ? '已发送' : '已跳过'}
                    </span>
                    <span className="text-sm text-gray-500">{d.professor_name} @ {d.professor_university}</span>
                  </div>
                  <h4 className="font-medium text-gray-900 truncate">{d.subject}</h4>
                  <p className="mt-1 text-sm text-gray-500 line-clamp-2">{d.body}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => setPreviewId(d.id)} className="rounded-lg border p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50" title="预览">
                    <Eye className="h-4 w-4" />
                  </button>
                  {d.status === 'pending' && (
                    <>
                      <button onClick={() => startEdit(d)} className="rounded-lg border p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50" title="编辑">
                        <Edit3 className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleSend(d.id)} className="rounded-lg bg-green-600 p-2 text-white hover:bg-green-700" title="发送">
                        <Send className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleSkip(d.id)} className="rounded-lg border p-2 text-gray-400 hover:text-orange-600 hover:bg-orange-50" title="跳过">
                        <SkipForward className="h-4 w-4" />
                      </button>
                    </>
                  )}
                  <button onClick={() => handleDelete(d.id)} className="rounded-lg border p-2 text-gray-400 hover:text-red-600 hover:bg-red-50" title="删除">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
