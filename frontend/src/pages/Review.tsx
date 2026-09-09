import { useEffect, useMemo, useState } from 'react'
import {
  ArrowUpDown,
  CheckCircle2,
  ChevronRight,
  Edit3,
  ExternalLink,
  Eye,
  Loader2,
  Search,
  Send,
  Sparkles,
  X,
} from 'lucide-react'
import ProfessorDetail from '../components/ProfessorDetail'
import { getDraftReview, getProfessor, sendEmail, startCompose, updateDraft } from '../services/api'

type SortMode = 'priority' | 'relevance' | 'reply'

interface Props {
  wsMessages: any[]
}

const scoreTone = (score: number) => {
  if (score >= 82) return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (score >= 70) return 'text-blue-700 bg-blue-50 border-blue-200'
  if (score >= 58) return 'text-amber-700 bg-amber-50 border-amber-200'
  return 'text-red-700 bg-red-50 border-red-200'
}

function ScoreBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="grid grid-cols-[5rem_minmax(5rem,1fr)_2.25rem] items-center gap-2 text-xs">
      <span className="text-gray-500">{label}</span>
      <div className="h-1.5 overflow-hidden rounded-full bg-gray-100">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-right font-semibold tabular-nums text-gray-700">{value}</span>
    </div>
  )
}

export default function Review({ wsMessages }: Props) {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [sortMode, setSortMode] = useState<SortMode>('relevance')
  const [region, setRegion] = useState('')
  const [query, setQuery] = useState('')
  const [previewId, setPreviewId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [recentlySavedId, setRecentlySavedId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState({ subject: '', body: '' })
  const [busyId, setBusyId] = useState<number | null>(null)
  const [composing, setComposing] = useState(false)
  const [ccDraftIds, setCcDraftIds] = useState<Set<number>>(new Set())

  const setDraftCc = (id: number, checked: boolean) => {
    setCcDraftIds((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }
  const [detailProfessor, setDetailProfessor] = useState<any | null>(null)
  const [detailLoadingId, setDetailLoadingId] = useState<number | null>(null)

  const fetchData = async () => {
    setLoading(true)
    try {
      const response = await getDraftReview(status)
      setItems(Array.isArray(response.data) ? response.data : [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [status])

  const regions = useMemo(
    () => Array.from(new Set(items.map((item) => item.professor_region).filter(Boolean))).sort(),
    [items],
  )

  const visibleItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    const filtered = items.filter((item) => {
      if (item.id === recentlySavedId) return true
      if (region && item.professor_region !== region) return false
      if (!normalizedQuery) return true
      return [
        item.professor_name,
        item.professor_university,
        item.subject,
        item.selected_paper?.title,
      ].some((value) => String(value || '').toLowerCase().includes(normalizedQuery))
    })
    const scoreKey = sortMode === 'relevance'
      ? 'relevance_score'
      : sortMode === 'reply'
        ? 'reply_likelihood_score'
        : 'priority_score'
    return [...filtered].sort((left, right) => Number(right[scoreKey]) - Number(left[scoreKey]))
  }, [items, query, recentlySavedId, region, sortMode])

  const averages = useMemo(() => {
    if (!visibleItems.length) return { relevance: 0, ready: 0 }
    const average = (key: string) => Math.round(
      visibleItems.reduce((sum, item) => sum + Number(item[key] || 0), 0) / visibleItems.length,
    )
    return {
      relevance: average('relevance_score'),
      ready: visibleItems.filter((item) => Number(item.priority_score) >= 70).length,
    }
  }, [visibleItems])

  const preview = items.find((item) => item.id === previewId)

  const openPreview = (item: any) => setPreviewId(item.id)

  const handleCompose = async () => {
    setComposing(true)
    try {
      await startCompose()
      setTimeout(fetchData, 3000)
    } finally {
      setTimeout(() => setComposing(false), 5000)
    }
  }

  const startEdit = (item: any) => {
    setPreviewId(null)
    setEditingId(item.id)
    setEditForm({ subject: item.subject || '', body: item.body || '' })
  }

  const saveEdit = async () => {
    if (editingId === null) return
    const draftId = editingId
    setBusyId(draftId)
    try {
      const response = await updateDraft(draftId, editForm)
      setItems((current) => current.map((item) => (
        item.id === draftId ? { ...item, ...response.data } : item
      )))
      setRecentlySavedId(draftId)
      setEditingId(null)
    } catch (error: any) {
      alert(error.response?.data?.detail || error.message || '草稿保存失败')
    } finally {
      setBusyId(null)
    }
  }

  const handleSend = async (id: number) => {
    const includeCc = ccDraftIds.has(id)
    if (!confirm(includeCc ? '确认发送这封邮件并抄送吗？' : '确认发送这封邮件吗？')) return
    setBusyId(id)
    try {
      await sendEmail(id, includeCc)
      await fetchData()
    } catch (error: any) {
      alert(error.response?.data?.detail || '发送失败')
    } finally {
      setBusyId(null)
    }
  }

  const openProfessorDetail = async (professorId: number) => {
    setDetailLoadingId(professorId)
    try {
      const response = await getProfessor(professorId)
      setPreviewId(null)
      setDetailProfessor(response.data)
    } catch (error: any) {
      alert(error.response?.data?.detail || '导师详情加载失败')
    } finally {
      setDetailLoadingId(null)
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">邮件草稿</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={status}
            onChange={(event) => {
              setRecentlySavedId(null)
              setStatus(event.target.value)
            }}
            className="h-10 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700"
          >
            <option value="">全部</option>
            <option value="pending">待发送</option>
            <option value="sent">已发送</option>
            <option value="skipped">已跳过</option>
          </select>
          <select
            value={sortMode}
            onChange={(event) => {
              setRecentlySavedId(null)
              setSortMode(event.target.value as SortMode)
            }}
            className="h-10 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700"
          >
            <option value="relevance">研究匹配度</option>
            <option value="priority">综合优先级</option>
            <option value="reply">回复倾向</option>
          </select>
          <button
            onClick={handleCompose}
            disabled={composing}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {composing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {composing ? '生成中...' : '生成草稿'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 border-y border-gray-200 bg-white">
        {[
          ['当前结果', visibleItems.length],
          ['平均匹配度', averages.relevance],
          ['优先审核', averages.ready],
        ].map(([label, value], index) => (
          <div key={String(label)} className={`px-4 py-3 ${index > 0 ? 'border-l border-gray-200' : ''}`}>
            <div className="text-xs text-gray-500">{label}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-gray-900">{value}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <label className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
          <input
            value={query}
            onChange={(event) => {
              setRecentlySavedId(null)
              setQuery(event.target.value)
            }}
            placeholder="搜索导师、学校、标题或论文"
            className="h-10 w-full rounded-md border border-gray-300 bg-white pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </label>
        <select
          value={region}
          onChange={(event) => {
            setRecentlySavedId(null)
            setRegion(event.target.value)
          }}
          className="h-10 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 sm:w-48"
        >
          <option value="">全部地区</option>
          {regions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <button
          onClick={() => {
            setRecentlySavedId(null)
            setSortMode(sortMode === 'priority' ? 'relevance' : sortMode === 'relevance' ? 'reply' : 'priority')
          }}
          className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-gray-300 bg-white text-gray-500 hover:bg-gray-50"
          title="切换排序"
          aria-label="切换排序"
        >
          <ArrowUpDown className="h-4 w-4" />
        </button>
      </div>

      <div className="overflow-hidden rounded-md border border-gray-200 bg-white">
        {loading ? (
          <div className="flex h-48 items-center justify-center">
            <Loader2 className="h-7 w-7 animate-spin text-blue-600" />
          </div>
        ) : visibleItems.length === 0 ? (
          <div className="px-6 py-16 text-center text-sm text-gray-500">没有符合条件的邮件</div>
        ) : visibleItems.map((item, index) => (
          <article
            key={item.id}
            className={`grid gap-4 p-4 sm:p-5 lg:grid-cols-[5rem_minmax(0,1fr)_16rem_auto] lg:items-center ${index ? 'border-t border-gray-200' : ''}`}
          >
            <div className={`flex h-16 w-16 flex-col items-center justify-center rounded-full border ${scoreTone(item.relevance_score)}`}>
              <span className="text-xl font-bold tabular-nums">{item.relevance_score}</span>
              <span className="text-[10px]">匹配</span>
            </div>

            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <button
                  type="button"
                  onClick={() => openProfessorDetail(item.professor_id)}
                  disabled={detailLoadingId === item.professor_id}
                  className="inline-flex min-w-0 items-center gap-0.5 font-semibold text-gray-900 hover:text-blue-700"
                  title="查看导师详情"
                >
                  <span className="truncate">{item.professor_name}</span>
                  {detailLoadingId === item.professor_id
                    ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                    : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                </button>
                <span className="text-xs text-gray-500">{item.professor_university}</span>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${scoreTone(item.priority_score)}`}>
                  {item.priority_label}
                </span>
              </div>
              <p className="mt-1 truncate text-sm font-medium text-gray-800">{item.subject}</p>
              {item.selected_paper ? (
                <div className="mt-2 flex min-w-0 items-center gap-1.5 text-xs text-gray-500">
                  <span className="shrink-0">展开作品</span>
                  <a
                    href={item.selected_paper.url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate font-medium text-blue-700 hover:underline"
                  >
                    {item.selected_paper.title}
                  </a>
                  <ExternalLink className="h-3 w-3 shrink-0" />
                </div>
              ) : (
                <p className="mt-2 text-xs font-medium text-red-600">未匹配到正文中的推荐作品</p>
              )}
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                {item.strengths?.slice(0, 2).map((value: string) => (
                  <span key={value} className="inline-flex items-center gap-1 text-emerald-700">
                    <CheckCircle2 className="h-3 w-3" />{value}
                  </span>
                ))}
                {item.cautions?.slice(0, 1).map((value: string) => (
                  <span key={value} className="text-amber-700">{value}</span>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <ScoreBar label="研究相关性" value={item.relevance_score} color="bg-blue-600" />
              <ScoreBar label="回复倾向" value={item.reply_likelihood_score} color="bg-emerald-600" />
              <div className="text-right text-[11px] text-gray-400">{item.content_length} {item.length_unit}</div>
            </div>

            <div className="flex items-center gap-2 lg:justify-end">
              <button
                onClick={() => openPreview(item)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-300 text-gray-500 hover:bg-gray-50"
                title="预览"
                aria-label="预览"
              >
                <Eye className="h-4 w-4" />
              </button>
              {item.status === 'pending' && (
                <>
                  <button
                    onClick={() => startEdit(item)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-300 text-gray-500 hover:bg-gray-50"
                    title="编辑"
                    aria-label="编辑"
                  >
                    <Edit3 className="h-4 w-4" />
                  </button>
                  <label className="inline-flex h-9 items-center gap-1.5 rounded-md border border-gray-300 px-2 text-xs text-gray-600">
                    <input
                      type="checkbox"
                      checked={ccDraftIds.has(item.id)}
                      onChange={(event) => setDraftCc(item.id, event.target.checked)}
                      className="rounded border-gray-300 text-emerald-600"
                    />
                    抄送
                  </label>
                  <button
                    onClick={() => handleSend(item.id)}
                    disabled={busyId === item.id}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                    title="发送"
                    aria-label="发送"
                  >
                    {busyId === item.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-md bg-white shadow-xl">
            <div className="sticky top-0 flex items-center justify-between border-b bg-white px-5 py-4">
              <div className="min-w-0">
                <button
                  type="button"
                  onClick={() => openProfessorDetail(preview.professor_id)}
                  disabled={detailLoadingId === preview.professor_id}
                  className="inline-flex min-w-0 items-center gap-0.5 font-semibold text-gray-900 hover:text-blue-700"
                  title="查看导师详情"
                >
                  <span className="truncate">{preview.professor_name}</span>
                  {detailLoadingId === preview.professor_id
                    ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                    : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                </button>
                <p className="truncate text-xs text-gray-500">{preview.professor_email}</p>
              </div>
              <div className="flex items-center gap-2">
                {preview.status === 'pending' && (
                  <button
                    onClick={() => startEdit(preview)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-md border text-gray-500"
                    title="编辑"
                    aria-label="编辑"
                  ><Edit3 className="h-4 w-4" /></button>
                )}
                <button
                  onClick={() => setPreviewId(null)}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-md border text-gray-500"
                  title="关闭"
                  aria-label="关闭"
                ><X className="h-4 w-4" /></button>
              </div>
            </div>
            <div className="space-y-5 px-5 py-5 sm:px-8">
              <div>
                <div className="text-xs font-medium uppercase text-gray-400">Subject</div>
                <div className="mt-1 font-medium text-gray-900">{preview.subject}</div>
              </div>
              <div className="whitespace-pre-wrap border-t pt-5 text-[15px] leading-7 text-gray-800">{preview.body}</div>
            </div>
          </div>
        </div>
      )}

      {editingId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-3xl rounded-md bg-white shadow-xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h3 className="font-semibold text-gray-900">编辑邮件</h3>
              <button
                onClick={() => setEditingId(null)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border text-gray-500"
                title="关闭"
                aria-label="关闭"
              ><X className="h-4 w-4" /></button>
            </div>
            <div className="space-y-4 p-5">
              <input
                value={editForm.subject}
                onChange={(event) => setEditForm({ ...editForm, subject: event.target.value })}
                className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <textarea
                value={editForm.body}
                onChange={(event) => setEditForm({ ...editForm, body: event.target.value })}
                rows={18}
                className="w-full resize-y rounded-md border border-gray-300 px-3 py-3 font-mono text-sm leading-6 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div className="flex justify-end gap-2 border-t px-5 py-4">
              <button onClick={() => setEditingId(null)} className="h-9 rounded-md border px-4 text-sm text-gray-600">取消</button>
              <button
                onClick={saveEdit}
                disabled={busyId === editingId}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busyId === editingId && <Loader2 className="h-4 w-4 animate-spin" />}
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {detailProfessor && (
        <ProfessorDetail
          professor={detailProfessor}
          onClose={() => setDetailProfessor(null)}
          onUpdate={fetchData}
          wsMessages={wsMessages}
        />
      )}
    </div>
  )
}
