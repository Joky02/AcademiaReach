import { useState, useEffect, useRef } from 'react'
import {
  X, Mail, Send, FileText, ExternalLink, MapPin,
  GraduationCap, Loader2, CheckCircle2, AlertCircle,
  Pencil, Save, RefreshCw, MessageSquareReply, Clock,
} from 'lucide-react'
import {
  deleteDraft, getDrafts, getProfessor, getReplies, sendEmail,
  startCompose, startEnrichProfessor, updateDraft, updateProfessor,
} from '../services/api'
import { nameToGradient, getInitials } from '../utils/avatar'

interface Professor {
  id: number
  name: string
  email: string
  university: string
  department?: string
  homepage?: string
  google_scholar?: string
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
  const [currentProfessor, setCurrentProfessor] = useState<Professor | null>(professor)
  const [drafts, setDrafts] = useState<any[]>([])
  const [replies, setReplies] = useState<any[]>([])
  const [previewDraft, setPreviewDraft] = useState<any | null>(null)
  const [activeSection, setActiveSection] = useState<'profile' | 'drafts' | 'conversation'>('drafts')
  const [editingDraftId, setEditingDraftId] = useState<number | null>(null)
  const [draftForm, setDraftForm] = useState({ subject: '', body: '' })
  const [savingDraft, setSavingDraft] = useState(false)
  const [loading, setLoading] = useState(false)
  const [composing, setComposing] = useState(false)
  const [sending, setSending] = useState<number | null>(null)
  const [sendResult, setSendResult] = useState<{ id: number; ok: boolean; msg: string } | null>(null)

  // Edit mode
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const [enrichMessage, setEnrichMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const lastComposeMessageRef = useRef<any>(null)
  const lastEnrichMessageRef = useRef<any>(null)

  const refreshRelatedData = async (targetOverride?: Professor | null) => {
    const target = targetOverride || currentProfessor || professor
    if (!target) return
    setLoading(true)
    try {
      const [draftRes, replyRes] = await Promise.all([getDrafts(), getReplies()])
      const targetDrafts = draftRes.data.filter((d: any) => d.professor_id === target.id)
      setDrafts(targetDrafts)
      setPreviewDraft((current: any) => {
        if (current) {
          return targetDrafts.find((draft: any) => draft.id === current.id) || targetDrafts[0] || null
        }
        return targetDrafts[0] || null
      })
      setReplies(replyRes.data.filter((r: any) => r.professor_id === target.id))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setCurrentProfessor(professor)
    setEnrichMessage(null)
    setActiveSection('drafts')
    setEditingDraftId(null)
    refreshRelatedData(professor)
  }, [professor])

  // Listen for compose completion
  useEffect(() => {
    if (!wsMessages.length) return
    const latest = wsMessages[wsMessages.length - 1]
    if (lastComposeMessageRef.current === latest) return
    lastComposeMessageRef.current = latest
    if (latest.channel === 'compose' && (latest.type === 'done' || latest.type === 'draft')) {
      const targetId = professor?.id
      if (latest.type === 'draft' && latest.data?.professor_id && latest.data.professor_id !== targetId) return
      if (targetId) {
        refreshRelatedData().then(() => {
          setComposing(false)
        })
      }
    }
  }, [wsMessages, professor?.id])

  // Listen for enrich progress/completion for this professor
  useEffect(() => {
    if (!wsMessages.length) return
    const target = currentProfessor || professor
    if (!target) return
    const latest = wsMessages[wsMessages.length - 1]
    if (lastEnrichMessageRef.current === latest) return
    lastEnrichMessageRef.current = latest
    if (latest.channel !== 'enrich' || latest.professor_id !== target.id) return

    if (latest.type === 'progress') {
      setEnriching(true)
      setEnrichMessage({ ok: true, text: latest.message || '补全中...' })
    }
    if (latest.type === 'done') {
      getProfessor(target.id).then((res) => {
        setCurrentProfessor(res.data)
        onUpdate?.()
      })
      const fields = latest.updated_fields || []
      setEnrichMessage({
        ok: true,
        text: fields.length > 0 ? `已更新：${fields.join(', ')}` : '补全完成，但没有发现新字段',
      })
      setEnriching(false)
    }
    if (latest.type === 'error') {
      setEnrichMessage({ ok: false, text: latest.message || '自动补全失败' })
      setEnriching(false)
    }
  }, [wsMessages, professor?.id, onUpdate])

  // Init edit form when entering edit mode
  const startEditing = () => {
    const target = currentProfessor || professor
    if (!target) return
    setEditForm({
      name: target.name || '',
      email: target.email || '',
      university: target.university || '',
      department: target.department || '',
      homepage: target.homepage || '',
      google_scholar: target.google_scholar || '',
      research_summary: target.research_summary || '',
      recent_papers: target.recent_papers || '',
      region: target.region || '',
    })
    setEditing(true)
  }

  const handleSave = async () => {
    const target = currentProfessor || professor
    if (!target) return
    setSaving(true)
    try {
      const changed: Record<string, string> = {}
      for (const [k, v] of Object.entries(editForm)) {
        if (v !== ((target as any)[k] || '')) changed[k] = v
      }
      if (Object.keys(changed).length > 0) {
        await updateProfessor(target.id, changed)
        const fresh = await getProfessor(target.id)
        setCurrentProfessor(fresh.data)
        onUpdate?.()
      }
      setEditing(false)
    } catch { /* ignore */ }
    setSaving(false)
  }

  const handleEnrich = async () => {
    const target = currentProfessor || professor
    if (!target) return
    setEnriching(true)
    setEnrichMessage(null)
    try {
      await startEnrichProfessor(target.id)
      setEnrichMessage({ ok: true, text: '补全任务已启动' })
    } catch (e: any) {
      setEnrichMessage({ ok: false, text: e.response?.data?.detail || e.message || '自动补全失败' })
      setEnriching(false)
    }
  }

  const view = currentProfessor || professor
  if (!view) return null

  const initials = getInitials(view.name)
  const gradient = nameToGradient(view.name)

  const hasSent = drafts.some((d) => d.status === 'sent')
  const hasPending = drafts.some((d) => d.status === 'pending')

  const EDITABLE_FIELDS: { key: string; label: string }[] = [
    { key: 'name', label: '姓名' },
    { key: 'email', label: '邮箱' },
    { key: 'university', label: '学校' },
    { key: 'department', label: '院系' },
    { key: 'homepage', label: '主页' },
    { key: 'google_scholar', label: 'Google Scholar' },
    { key: 'region', label: '地区' },
    { key: 'research_summary', label: '研究方向' },
    { key: 'recent_papers', label: '近期论文' },
  ]

  const handleCompose = async () => {
    setComposing(true)
    try {
      await startCompose([view.id])
    } catch {
      setComposing(false)
    }
  }

  const handleDeleteDraft = async (draftId: number) => {
    if (!confirm('确定删除这条草稿吗？')) return
    await deleteDraft(draftId)
    if (editingDraftId === draftId) setEditingDraftId(null)
    await refreshRelatedData()
  }

  const startDraftEditing = (draft: any) => {
    setPreviewDraft(draft)
    setDraftForm({ subject: draft.subject || '', body: draft.body || '' })
    setEditingDraftId(draft.id)
  }

  const saveDraftEditing = async () => {
    if (editingDraftId === null) return
    setSavingDraft(true)
    try {
      await updateDraft(editingDraftId, draftForm)
      setEditingDraftId(null)
      await refreshRelatedData()
    } finally {
      setSavingDraft(false)
    }
  }

  const handleSend = async (draftId: number) => {
    setSending(draftId)
    setSendResult(null)
    try {
      await sendEmail(draftId)
      setSendResult({ id: draftId, ok: true, msg: '发送成功' })
      await refreshRelatedData()
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

  const timeValue = (value?: string) => {
    if (!value) return 0
    const ts = new Date(value).getTime()
    return Number.isNaN(ts) ? 0 : ts
  }

  const formatTime = (value?: string) => {
    if (!value) return '时间未知'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '时间未知'
    return date.toLocaleString('zh-CN')
  }

  const conversationItems = [
    ...drafts
      .filter((d) => d.status === 'sent')
      .map((d) => ({
        id: `draft-${d.id}`,
        kind: 'outgoing',
        subject: d.subject || '(无主题)',
        body: d.body || '',
        at: d.sent_at || d.created_at,
        meta: '已发送邮件',
      })),
    ...replies.map((r) => ({
      id: `reply-${r.id}`,
      kind: 'incoming',
      subject: r.subject || '(无主题)',
      body: r.body || '',
      at: r.received_at,
      meta: r.is_read ? '导师回复' : '未读回复',
    })),
  ].sort((a, b) => timeValue(a.at) - timeValue(b.at))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-2 backdrop-blur-sm sm:p-5">
      <div className="relative flex h-[calc(100vh-1rem)] w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-white shadow-2xl sm:h-[90vh]">
        <header className="flex shrink-0 items-center gap-4 border-b border-gray-200 px-4 py-4 sm:px-6">
          <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${gradient} text-base font-bold text-white`}>
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold text-gray-950">{view.name}</h2>
              {hasSent ? (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">已发邮件</span>
              ) : hasPending ? (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">草稿待发</span>
              ) : (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">未生成</span>
              )}
              {view.reply_status && view.reply_status !== 'no_reply' && (
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                  {replyLabel[view.reply_status] || view.reply_status}
                </span>
              )}
            </div>
            <p className="mt-0.5 truncate text-sm text-gray-500">
              {view.university}{view.department ? ` · ${view.department}` : ''}
            </p>
          </div>
          <button
            onClick={onClose}
            title="关闭"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <aside className={`${activeSection === 'profile' ? 'block' : 'hidden'} min-h-0 flex-1 overflow-y-auto border-b border-gray-200 bg-white lg:block lg:w-[340px] lg:flex-none lg:shrink-0 lg:border-b-0 lg:border-r`}>
            <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
              <p className="text-sm font-semibold text-gray-900">导师资料</p>
              <div className="flex items-center gap-1">
                <button
                  onClick={handleEnrich}
                  disabled={enriching}
                  title="自动补全信息"
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-50"
                >
                  {enriching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                </button>
                {!editing ? (
                  <button
                    onClick={startEditing}
                    title="编辑导师资料"
                    className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                ) : (
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    title="保存导师资料"
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  </button>
                )}
              </div>
            </div>
            <div className="flex gap-1 border-b border-gray-100 px-3 py-2 lg:hidden">
              <button className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white">
                资料
              </button>
              <button
                onClick={() => setActiveSection('drafts')}
                className="rounded-lg px-3 py-2 text-sm font-medium text-gray-500 hover:bg-gray-100"
              >
                草稿 {drafts.length}
              </button>
              <button
                onClick={() => setActiveSection('conversation')}
                className="rounded-lg px-3 py-2 text-sm font-medium text-gray-500 hover:bg-gray-100"
              >
                对话 {conversationItems.length}
              </button>
            </div>

            <div className="space-y-5 px-5 py-4">
              {enrichMessage && (
                <div className={`rounded-lg px-3 py-2 text-xs ${
                  enrichMessage.ok ? 'bg-indigo-50 text-indigo-700' : 'bg-red-50 text-red-600'
                }`}>
                  {enrichMessage.text}
                </div>
              )}

              {editing ? (
                <div className="space-y-3">
                  {EDITABLE_FIELDS.map(({ key, label }) => (
                    <div key={key}>
                      <label className="mb-1 block text-xs font-medium text-gray-500">{label}</label>
                      {key === 'research_summary' || key === 'recent_papers' ? (
                        <textarea
                          value={editForm[key] || ''}
                          onChange={(e) => setEditForm({ ...editForm, [key]: e.target.value })}
                          rows={key === 'recent_papers' ? 4 : 3}
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
                  <button
                    onClick={() => setEditing(false)}
                    className="text-xs text-gray-500 hover:text-gray-800"
                  >
                    取消编辑
                  </button>
                </div>
              ) : (
                <>
                  <div className="space-y-3">
                    <div>
                      <p className="text-xs font-medium text-gray-400">邮箱</p>
                      {!view.email || view.email.includes('@tbd') || view.email.startsWith('http') ? (
                        <p className="mt-1 text-sm text-amber-600">待补充</p>
                      ) : (
                        <a href={`mailto:${view.email}`} className="mt-1 inline-flex max-w-full items-center gap-1.5 text-sm text-indigo-600 hover:underline">
                          <Mail className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{view.email}</span>
                        </a>
                      )}
                    </div>
                    {view.region && (
                      <div>
                        <p className="text-xs font-medium text-gray-400">地区</p>
                        <p className="mt-1 flex items-center gap-1.5 text-sm text-gray-700">
                          <MapPin className="h-3.5 w-3.5 text-gray-400" />
                          {view.region}
                        </p>
                      </div>
                    )}
                    <div className="flex flex-wrap gap-2 border-t border-gray-100 pt-3">
                      {view.homepage && (
                        <a
                          href={view.homepage}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-indigo-200 hover:text-indigo-600"
                        >
                          <ExternalLink className="h-3.5 w-3.5" /> 主页
                        </a>
                      )}
                      {view.google_scholar && (
                        <a
                          href={view.google_scholar}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-indigo-200 hover:text-indigo-600"
                        >
                          <GraduationCap className="h-3.5 w-3.5" /> Scholar
                        </a>
                      )}
                    </div>
                  </div>

                  <div className="border-t border-gray-100 pt-4">
                    <p className="text-xs font-medium text-gray-400">研究方向</p>
                    <p className="mt-1.5 text-sm leading-6 text-gray-700">{view.research_summary || '暂无研究方向信息'}</p>
                  </div>

                  <div className="border-t border-gray-100 pt-4">
                    <p className="text-xs font-medium text-gray-400">近期论文</p>
                    <p className="mt-1.5 whitespace-pre-line text-sm leading-6 text-gray-600">
                      {view.recent_papers ? view.recent_papers.replace(/;/g, '\n') : '暂无论文信息'}
                    </p>
                  </div>
                </>
              )}
            </div>
          </aside>

          <section className={`${activeSection === 'profile' ? 'hidden' : 'flex'} min-h-0 min-w-0 flex-1 flex-col bg-gray-50 lg:flex`}>
            <div className="flex shrink-0 items-center justify-between border-b border-gray-200 bg-white px-3 sm:px-5">
              <nav className="flex min-w-0 items-center gap-1 py-2">
                <button
                  onClick={() => setActiveSection('profile')}
                  className="rounded-lg px-3 py-2 text-sm font-medium text-gray-500 hover:bg-gray-100 lg:hidden"
                >
                  资料
                </button>
                <button
                  onClick={() => setActiveSection('drafts')}
                  className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                    activeSection === 'drafts' ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-100'
                  }`}
                >
                  <FileText className="h-4 w-4" />
                  草稿
                  <span className={activeSection === 'drafts' ? 'text-gray-300' : 'text-gray-400'}>{drafts.length}</span>
                </button>
                <button
                  onClick={() => setActiveSection('conversation')}
                  className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                    activeSection === 'conversation' ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-100'
                  }`}
                >
                  <MessageSquareReply className="h-4 w-4" />
                  对话
                  <span className={activeSection === 'conversation' ? 'text-gray-300' : 'text-gray-400'}>{conversationItems.length}</span>
                </button>
              </nav>
              {activeSection === 'drafts' && (
                <button
                  onClick={handleCompose}
                  disabled={composing}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {composing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
                  <span className="hidden sm:inline">{composing ? '生成中...' : '生成邮件'}</span>
                </button>
              )}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5">
              {loading ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
                </div>
              ) : activeSection === 'drafts' ? (
                drafts.length === 0 ? (
                  <div className="flex h-full min-h-72 flex-col items-center justify-center text-center">
                    <Mail className="h-10 w-10 text-gray-300" />
                    <p className="mt-3 text-sm font-medium text-gray-700">还没有邮件草稿</p>
                    <p className="mt-1 text-xs text-gray-400">生成后可直接在这里检查、修改和发送。</p>
                    <button
                      onClick={handleCompose}
                      disabled={composing}
                      className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {composing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                      {composing ? '生成中...' : '生成邮件'}
                    </button>
                  </div>
                ) : (
                  <div className="grid min-h-full gap-4 xl:grid-cols-[250px_minmax(0,1fr)]">
                    <div className="space-y-2">
                      {drafts.map((draft) => (
                        <button
                          key={draft.id}
                          onClick={() => {
                            setPreviewDraft(draft)
                            setEditingDraftId(null)
                          }}
                          className={`w-full rounded-lg border p-3 text-left transition-colors ${
                            previewDraft?.id === draft.id
                              ? 'border-indigo-300 bg-indigo-50'
                              : 'border-gray-200 bg-white hover:border-gray-300'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusColor(draft.status)}`}>
                              {statusLabel(draft.status)}
                            </span>
                            <span className="text-[10px] text-gray-400">{draft.language === 'cn' ? '中文' : 'English'}</span>
                          </div>
                          <p className="mt-2 line-clamp-2 text-sm font-medium leading-5 text-gray-800">{draft.subject}</p>
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{draft.body}</p>
                        </button>
                      ))}
                    </div>

                    {previewDraft && (
                      <article className="min-w-0 rounded-lg border border-gray-200 bg-white">
                        {editingDraftId === previewDraft.id ? (
                          <div className="space-y-4 p-4 sm:p-6">
                            <div>
                              <label className="mb-1 block text-xs font-medium text-gray-500">主题</label>
                              <input
                                value={draftForm.subject}
                                onChange={(e) => setDraftForm({ ...draftForm, subject: e.target.value })}
                                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                              />
                            </div>
                            <div>
                              <label className="mb-1 block text-xs font-medium text-gray-500">正文</label>
                              <textarea
                                value={draftForm.body}
                                onChange={(e) => setDraftForm({ ...draftForm, body: e.target.value })}
                                rows={18}
                                className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm leading-6 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                              />
                            </div>
                            <div className="flex justify-end gap-2">
                              <button
                                onClick={() => setEditingDraftId(null)}
                                className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
                              >
                                取消
                              </button>
                              <button
                                onClick={saveDraftEditing}
                                disabled={savingDraft}
                                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                              >
                                {savingDraft ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                保存
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="border-b border-gray-100 px-4 py-4 sm:px-6">
                              <div className="flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="text-xs text-gray-400">主题</p>
                                  <h3 className="mt-1 text-base font-semibold leading-6 text-gray-900">{previewDraft.subject || '(无主题)'}</h3>
                                </div>
                                <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-medium ${statusColor(previewDraft.status)}`}>
                                  {statusLabel(previewDraft.status)}
                                </span>
                              </div>
                              <p className="mt-3 text-xs text-gray-500">
                                收件人：<span className="text-gray-700">{view.name} &lt;{view.email}&gt;</span>
                              </p>
                            </div>
                            <div className="whitespace-pre-wrap px-4 py-5 text-sm leading-7 text-gray-800 sm:px-6">
                              {previewDraft.body}
                            </div>
                            <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 px-4 py-3 sm:px-6">
                              {previewDraft.status === 'pending' && (
                                <>
                                  <button
                                    onClick={() => startDraftEditing(previewDraft)}
                                    className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                                  >
                                    <Pencil className="h-3.5 w-3.5" /> 编辑
                                  </button>
                                  <button
                                    onClick={() => handleSend(previewDraft.id)}
                                    disabled={sending === previewDraft.id || view.email.includes('@tbd')}
                                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                                  >
                                    {sending === previewDraft.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                                    发送
                                  </button>
                                </>
                              )}
                              <button
                                onClick={() => handleDeleteDraft(previewDraft.id)}
                                className="ml-auto rounded-lg px-3 py-2 text-xs text-gray-400 hover:bg-red-50 hover:text-red-600"
                              >
                                删除
                              </button>
                              {sendResult && sendResult.id === previewDraft.id && (
                                <span className={`inline-flex items-center gap-1 text-xs ${sendResult.ok ? 'text-emerald-600' : 'text-red-500'}`}>
                                  {sendResult.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
                                  {sendResult.msg}
                                </span>
                              )}
                            </div>
                          </>
                        )}
                      </article>
                    )}
                  </div>
                )
              ) : conversationItems.length === 0 ? (
                <div className="flex h-full min-h-72 flex-col items-center justify-center text-center">
                  <MessageSquareReply className="h-10 w-10 text-gray-300" />
                  <p className="mt-3 text-sm font-medium text-gray-700">还没有邮件往来</p>
                  <p className="mt-1 text-xs text-gray-400">发送邮件或收到回复后，会按时间显示在这里。</p>
                </div>
              ) : (
                <div className="mx-auto max-w-3xl space-y-4">
                  {conversationItems.map((item) => (
                    <article
                      key={item.id}
                      className={`rounded-lg border p-4 sm:p-5 ${
                        item.kind === 'incoming'
                          ? 'border-blue-200 bg-blue-50/60'
                          : 'border-gray-200 bg-white'
                      }`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            item.kind === 'incoming' ? 'bg-blue-100 text-blue-700' : 'bg-emerald-100 text-emerald-700'
                          }`}>
                            {item.meta}
                          </span>
                          <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                            <Clock className="h-3 w-3" />
                            {formatTime(item.at)}
                          </span>
                        </div>
                      </div>
                      <h3 className="mt-3 text-sm font-semibold text-gray-900">{item.subject}</h3>
                      <div className="mt-3 whitespace-pre-wrap border-t border-black/5 pt-3 text-sm leading-7 text-gray-700">
                        {item.body || '无正文内容'}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
