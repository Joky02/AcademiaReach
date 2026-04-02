import { useState, useEffect } from 'react'
import {
  X, Mail, Send, FileText, ExternalLink, MapPin, Building2,
  GraduationCap, Loader2, CheckCircle2, AlertCircle, User,
  Pencil, Save, RefreshCw,
} from 'lucide-react'
import { getDrafts, startCompose, sendEmail, updateProfessor, enrichProfessor, deleteDraft } from '../services/api'

interface Professor {
  id: number
  name: string
  email: string
  university: string
  department?: string
  homepage?: string
  research_summary?: string
  recent_papers?: string
  region?: string
  source?: string
  reply_status?: string
}

interface Props {
  professor: Professor | null
  onClose: () => void
  onUpdate?: () => void
  wsMessages: any[]
}

export default function ProfessorDetail({ professor, onClose, onUpdate, wsMessages }: Props) {
  const [drafts, setDrafts] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [composing, setComposing] = useState(false)
  const [sending, setSending] = useState<number | null>(null)
  const [sendResult, setSendResult] = useState<{ id: number; ok: boolean; msg: string } | null>(null)

  // Edit mode
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [enriching, setEnriching] = useState(false)

  useEffect(() => {
    if (professor) {
      setLoading(true)
      getDrafts()
        .then((res) => {
          const filtered = res.data.filter((d: any) => d.professor_id === professor.id)
          setDrafts(filtered)
        })
        .finally(() => setLoading(false))
    }
  }, [professor])

  // Listen for compose completion
  useEffect(() => {
    if (!wsMessages.length) return
    const latest = wsMessages[wsMessages.length - 1]
    if (latest.channel === 'compose' && (latest.type === 'done' || latest.type === 'draft')) {
      if (professor) {
        getDrafts().then((res) => {
          setDrafts(res.data.filter((d: any) => d.professor_id === professor.id))
          setComposing(false)
        })
      }
    }
  }, [wsMessages, professor])

  // Init edit form when entering edit mode
  const startEditing = () => {
    if (!professor) return
    setEditForm({
      name: professor.name || '',
      email: professor.email || '',
      university: professor.university || '',
      department: professor.department || '',
      homepage: professor.homepage || '',
      research_summary: professor.research_summary || '',
      recent_papers: professor.recent_papers || '',
      region: professor.region || '',
    })
    setEditing(true)
  }

  const handleSave = async () => {
    if (!professor) return
    setSaving(true)
    try {
      const changed: Record<string, string> = {}
      for (const [k, v] of Object.entries(editForm)) {
        if (v !== ((professor as any)[k] || '')) changed[k] = v
      }
      if (Object.keys(changed).length > 0) {
        await updateProfessor(professor.id, changed)
        onUpdate?.()
      }
      setEditing(false)
    } catch { /* ignore */ }
    setSaving(false)
  }

  const handleEnrich = async () => {
    if (!professor) return
    setEnriching(true)
    try {
      await enrichProfessor(professor.id)
      onUpdate?.()
    } catch { /* ignore */ }
    setEnriching(false)
  }

  if (!professor) return null

  const initials = professor.name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  const hasSent = drafts.some((d) => d.status === 'sent')
  const hasPending = drafts.some((d) => d.status === 'pending')

  const EDITABLE_FIELDS: { key: string; label: string }[] = [
    { key: 'name', label: '姓名' },
    { key: 'email', label: '邮箱' },
    { key: 'university', label: '学校' },
    { key: 'department', label: '院系' },
    { key: 'homepage', label: '主页' },
    { key: 'region', label: '地区' },
    { key: 'research_summary', label: '研究方向' },
    { key: 'recent_papers', label: '近期论文' },
  ]

  const handleCompose = async () => {
    setComposing(true)
    try {
      await startCompose([professor.id])
    } catch {
      setComposing(false)
    }
  }

  const handleDeleteDraft = async (draftId: number) => {
    if (!confirm('确定删除这条草稿吗？')) return
    await deleteDraft(draftId)
    if (professor) {
      const dRes = await getDrafts()
      setDrafts(dRes.data.filter((d: any) => d.professor_id === professor.id))
    }
  }

  const handleSend = async (draftId: number) => {
    setSending(draftId)
    setSendResult(null)
    try {
      const res = await sendEmail(draftId)
      setSendResult({ id: draftId, ok: true, msg: '发送成功' })
      // Refresh drafts
      const dRes = await getDrafts()
      setDrafts(dRes.data.filter((d: any) => d.professor_id === professor.id))
    } catch (e: any) {
      setSendResult({ id: draftId, ok: false, msg: e.response?.data?.detail || '发送失败' })
    } finally {
      setSending(null)
    }
  }

  const statusColor = (status: string) => {
    switch (status) {
      case 'sent': return 'bg-green-100 text-green-700'
      case 'pending': return 'bg-yellow-100 text-yellow-700'
      default: return 'bg-gray-100 text-gray-600'
    }
  }

  const statusLabel = (status: string) => {
    switch (status) {
      case 'sent': return '已发送'
      case 'pending': return '草稿'
      case 'approved': return '已审批'
      default: return status
    }
  }

  const replyLabel: Record<string, string> = {
    no_reply: '未回复', replied: '已回复', positive: '积极回复', negative: '消极回复',
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="relative w-[90vw] max-w-2xl max-h-[85vh] flex flex-col rounded-2xl bg-white shadow-2xl overflow-hidden">
        {/* Close */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 z-10 rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
        >
          <X className="h-5 w-5" />
        </button>

        {/* Header card */}
        <div className="bg-gradient-to-br from-indigo-500 to-purple-600 px-6 py-8 text-white">
          <div className="flex items-start gap-5">
            {/* Avatar */}
            <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-white/20 text-2xl font-bold backdrop-blur-sm">
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-2xl font-bold truncate">{professor.name}</h2>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-white/80">
                <span className="flex items-center gap-1">
                  <Building2 className="h-3.5 w-3.5" />
                  {professor.university}
                </span>
                {professor.department && (
                  <span className="flex items-center gap-1">
                    <GraduationCap className="h-3.5 w-3.5" />
                    {professor.department}
                  </span>
                )}
                {professor.region && (
                  <span className="flex items-center gap-1">
                    <MapPin className="h-3.5 w-3.5" />
                    {professor.region}
                  </span>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {hasSent && (
                  <span className="rounded-full bg-green-400/20 px-2.5 py-0.5 text-xs font-medium text-green-100">
                    ✓ 已发邮件
                  </span>
                )}
                {hasPending && !hasSent && (
                  <span className="rounded-full bg-yellow-400/20 px-2.5 py-0.5 text-xs font-medium text-yellow-100">
                    有草稿待发
                  </span>
                )}
                {!hasSent && !hasPending && (
                  <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-medium text-white/70">
                    未生成邮件
                  </span>
                )}
                {professor.reply_status && professor.reply_status !== 'no_reply' && (
                  <span className="rounded-full bg-blue-400/20 px-2.5 py-0.5 text-xs font-medium text-blue-100">
                    {replyLabel[professor.reply_status] || professor.reply_status}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Info — view / edit mode */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold text-gray-800">导师信息</p>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleEnrich}
                  disabled={enriching}
                  title="自动补全信息"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-50 transition-colors"
                >
                  {enriching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                  {enriching ? '补全中...' : '自动补全'}
                </button>
                {!editing ? (
                  <button
                    onClick={startEditing}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                  >
                    <Pencil className="h-3.5 w-3.5" /> 编辑
                  </button>
                ) : (
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50 transition-colors"
                  >
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                    保存
                  </button>
                )}
              </div>
            </div>

            {editing ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {EDITABLE_FIELDS.map(({ key, label }) => (
                  <div key={key} className={key === 'research_summary' || key === 'recent_papers' ? 'sm:col-span-2' : ''}>
                    <label className="block text-xs text-gray-500 mb-1">{label}</label>
                    {key === 'research_summary' || key === 'recent_papers' ? (
                      <textarea
                        value={editForm[key] || ''}
                        onChange={(e) => setEditForm({ ...editForm, [key]: e.target.value })}
                        rows={2}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                      />
                    ) : (
                      <input
                        type="text"
                        value={editForm[key] || ''}
                        onChange={(e) => setEditForm({ ...editForm, [key]: e.target.value })}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                      />
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-gray-100 p-3">
                    <p className="text-xs text-gray-500 mb-1">邮箱</p>
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {!professor.email || professor.email.includes('@tbd') || professor.email.startsWith('http') ? (
                        <span className="text-gray-400">待补充</span>
                      ) : (
                        <a href={`mailto:${professor.email}`} className="text-indigo-600 hover:underline">
                          {professor.email}
                        </a>
                      )}
                    </p>
                  </div>
                  {professor.homepage && (
                    <div className="rounded-lg border border-gray-100 p-3">
                      <p className="text-xs text-gray-500 mb-1">主页</p>
                      <a
                        href={professor.homepage}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sm text-indigo-600 hover:underline inline-flex items-center gap-1 truncate"
                      >
                        访问主页 <ExternalLink className="h-3 w-3 shrink-0" />
                      </a>
                    </div>
                  )}
                </div>

                {professor.research_summary && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-gray-500 mb-1">研究方向</p>
                    <p className="text-sm text-gray-700">{professor.research_summary}</p>
                  </div>
                )}

                {professor.recent_papers && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-gray-500 mb-1">近期论文</p>
                    <p className="text-sm text-gray-600 whitespace-pre-line">{professor.recent_papers.replace(/;/g, '\n')}</p>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Drafts section */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold text-gray-800">邮件草稿</p>
              <button
                onClick={handleCompose}
                disabled={composing}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50 transition-colors"
              >
                {composing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
                {composing ? '生成中...' : '生成邮件'}
              </button>
            </div>

            {loading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
              </div>
            ) : drafts.length === 0 ? (
              <div className="rounded-lg bg-gray-50 p-6 text-center text-sm text-gray-400">
                <Mail className="mx-auto h-8 w-8 text-gray-300 mb-2" />
                暂无草稿，点击"生成邮件"让 AI 撰写套磁信
              </div>
            ) : (
              <div className="space-y-3">
                {drafts.map((d) => (
                  <div key={d.id} className="rounded-lg border border-gray-200 p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-gray-800 truncate flex-1">{d.subject}</span>
                      <span className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(d.status)}`}>
                        {statusLabel(d.status)}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 mb-3 line-clamp-3 whitespace-pre-line">{d.body}</p>
                    <div className="flex items-center gap-2">
                      {d.status === 'pending' && (
                        <button
                          onClick={() => handleSend(d.id)}
                          disabled={sending === d.id || professor.email.includes('@tbd')}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
                        >
                          {sending === d.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                          发送邮件
                        </button>
                      )}
                      {sendResult && sendResult.id === d.id && (
                        <span className={`inline-flex items-center gap-1 text-xs ${sendResult.ok ? 'text-green-600' : 'text-red-500'}`}>
                          {sendResult.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
                          {sendResult.msg}
                        </span>
                      )}
                      <button
                        onClick={() => handleDeleteDraft(d.id)}
                        className="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                      >
                        <X className="h-3 w-3" /> 删除
                      </button>
                      <span className="text-xs text-gray-400">
                        {d.language === 'cn' ? '中文' : 'English'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
