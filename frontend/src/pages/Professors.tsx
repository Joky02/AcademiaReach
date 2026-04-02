import { useState, useEffect, useMemo } from 'react'
import {
  Search, Trash2, ExternalLink, Loader2, UserPlus, Globe,
  MapPin, Building2, Mail, FileText, Send, ChevronDown, ChevronRight, Bot,
  Star, Tag, Plus, X, RefreshCw,
} from 'lucide-react'
import {
  getProfessors, addProfessor, deleteProfessor, getDrafts,
  toggleStar, updateProfTags, enrichProfessor,
} from '../services/api'
import ProfessorDetail from '../components/ProfessorDetail'

interface Props {
  wsMessages: any[]
  searching: boolean
  searchLog: string[]
  onStartSearch: () => void
  onOpenSearchModal: () => void
  composing: boolean
  onStartCompose: () => void
}

// 地区显示名 & 排序权重
const REGION_LABELS: Record<string, string> = {
  China: '中国大陆', 'Hong Kong': '中国香港', Singapore: '新加坡',
  US: '美国', UK: '英国', CA: '加拿大', AU: '澳大利亚',
}
const REGION_ORDER = ['China', 'Hong Kong', 'Singapore', 'US', 'UK', 'CA', 'AU']

// 预设标签及颜色
const PRESET_TAGS: Record<string, { label: string; color: string }> = {
  '院士': { label: '院士', color: 'bg-red-100 text-red-700 border-red-200' },
  '杰青': { label: '杰青', color: 'bg-orange-100 text-orange-700 border-orange-200' },
  '优青': { label: '优青', color: 'bg-amber-100 text-amber-700 border-amber-200' },
  '长江学者': { label: '长江学者', color: 'bg-yellow-100 text-yellow-700 border-yellow-200' },
  '青千': { label: '青千', color: 'bg-lime-100 text-lime-700 border-lime-200' },
  'Fellow': { label: 'Fellow', color: 'bg-blue-100 text-blue-700 border-blue-200' },
  'AP': { label: 'AP', color: 'bg-sky-100 text-sky-700 border-sky-200' },
  'Associate Prof': { label: 'Assoc Prof', color: 'bg-teal-100 text-teal-700 border-teal-200' },
  'Full Prof': { label: 'Full Prof', color: 'bg-indigo-100 text-indigo-700 border-indigo-200' },
  '博导': { label: '博导', color: 'bg-purple-100 text-purple-700 border-purple-200' },
}

export default function Professors({
  wsMessages, searching, searchLog, onStartSearch, onOpenSearchModal, composing, onStartCompose,
}: Props) {
  const [professors, setProfessors] = useState<any[]>([])
  const [draftsMap, setDraftsMap] = useState<Record<number, any[]>>({})
  const [loading, setLoading] = useState(true)

  // Track newly added professor IDs (during this session)
  const [newProfIds, setNewProfIds] = useState<Set<number>>(new Set())

  // Detail modal
  const [selectedProf, setSelectedProf] = useState<any>(null)

  // Add form
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({
    name: '', email: '', university: '', department: '',
    homepage: '', research_summary: '', region: '',
  })

  // Collapsed regions
  const [collapsedRegions, setCollapsedRegions] = useState<Set<string>>(new Set())

  // Tag picker
  const [tagPickerProf, setTagPickerProf] = useState<number | null>(null)

  // Enriching professors (loading state)
  const [enrichingIds, setEnrichingIds] = useState<Set<number>>(new Set())

  const fetchData = () => {
    Promise.all([getProfessors(), getDrafts()])
      .then(([profRes, draftRes]) => {
        setProfessors(profRes.data)
        // Build professor_id → drafts map
        const dm: Record<number, any[]> = {}
        for (const d of draftRes.data) {
          if (!dm[d.professor_id]) dm[d.professor_id] = []
          dm[d.professor_id].push(d)
        }
        setDraftsMap(dm)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchData() }, [])

  // Listen for search/compose WebSocket messages — track new professors & refresh data
  useEffect(() => {
    if (wsMessages.length === 0) return
    const latest = wsMessages[wsMessages.length - 1]
    if (latest.channel === 'search') {
      if (latest.type === 'done' || latest.type === 'error') fetchData()
      if (latest.type === 'professor') {
        if (latest.data?.id) setNewProfIds((prev) => new Set(prev).add(latest.data.id))
        fetchData()
      }
    }
    if (latest.channel === 'compose') {
      if (latest.type === 'done' || latest.type === 'draft') fetchData()
    }
  }, [wsMessages])

  // Group professors by region → university
  const grouped = useMemo(() => {
    const regionMap: Record<string, Record<string, any[]>> = {}
    for (const p of professors) {
      const region = p.region || 'Other'
      const uni = p.university || 'Unknown'
      if (!regionMap[region]) regionMap[region] = {}
      if (!regionMap[region][uni]) regionMap[region][uni] = []
      regionMap[region][uni].push(p)
    }
    // Sort regions
    const sorted = Object.entries(regionMap).sort(([a], [b]) => {
      const ia = REGION_ORDER.indexOf(a)
      const ib = REGION_ORDER.indexOf(b)
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib)
    })
    return sorted
  }, [professors])

  const handleSearch = () => {
    setNewProfIds(new Set())
    onStartSearch()
  }

  const handleAdd = async () => {
    if (!form.name || !form.university) return
    const res = await addProfessor(form)
    setForm({ name: '', email: '', university: '', department: '', homepage: '', research_summary: '', region: '' })
    setShowAdd(false)
    fetchData()
    // Auto-enrich in background
    const newId = res.data?.id
    if (newId) {
      setEnrichingIds((prev) => new Set(prev).add(newId))
      enrichProfessor(newId)
        .then(() => fetchData())
        .catch(() => {})
        .finally(() => setEnrichingIds((prev) => { const s = new Set(prev); s.delete(newId); return s }))
    }
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确定删除这位导师吗？')) return
    await deleteProfessor(id)
    fetchData()
  }

  const handleEnrich = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    setEnrichingIds((prev) => new Set(prev).add(id))
    try {
      await enrichProfessor(id)
      fetchData()
    } catch { /* ignore */ }
    setEnrichingIds((prev) => { const s = new Set(prev); s.delete(id); return s })
  }

  const handleToggleStar = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    await toggleStar(id)
    fetchData()
  }

  const handleAddTag = async (e: React.MouseEvent, profId: number, tag: string) => {
    e.stopPropagation()
    const prof = professors.find((p) => p.id === profId)
    if (!prof) return
    const existing: string[] = parseTags(prof.tags)
    if (existing.includes(tag)) return
    await updateProfTags(profId, [...existing, tag])
    setTagPickerProf(null)
    fetchData()
  }

  const handleRemoveTag = async (e: React.MouseEvent, profId: number, tag: string) => {
    e.stopPropagation()
    const prof = professors.find((p) => p.id === profId)
    if (!prof) return
    const existing: string[] = parseTags(prof.tags)
    await updateProfTags(profId, existing.filter((t) => t !== tag))
    fetchData()
  }

  const parseTags = (raw: any): string[] => {
    if (Array.isArray(raw)) return raw
    if (typeof raw === 'string') {
      try { return JSON.parse(raw) } catch { return [] }
    }
    return []
  }

  const toggleRegion = (region: string) => {
    setCollapsedRegions((prev) => {
      const next = new Set(prev)
      next.has(region) ? next.delete(region) : next.add(region)
      return next
    })
  }

  const emailStatus = (profId: number) => {
    const ds = draftsMap[profId]
    if (!ds || ds.length === 0) return null
    if (ds.some((d: any) => d.status === 'sent')) return 'sent'
    return 'draft'
  }

  const initials = (name: string) =>
    name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()

  // Color palette for region headers
  const regionColors: Record<string, string> = {
    China: 'from-red-500 to-rose-600',
    'Hong Kong': 'from-pink-500 to-fuchsia-600',
    Singapore: 'from-emerald-500 to-teal-600',
    US: 'from-blue-500 to-indigo-600',
    UK: 'from-violet-500 to-purple-600',
    CA: 'from-orange-500 to-amber-600',
    AU: 'from-cyan-500 to-sky-600',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">导师管理</h2>
          <p className="text-sm text-gray-500 mt-0.5">共 {professors.length} 位导师</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleSearch}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 shadow-sm"
          >
            {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {searching ? '搜索中...' : 'Agent 搜索'}
          </button>
          {searching && (
            <button
              onClick={onOpenSearchModal}
              className="inline-flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100 animate-pulse"
            >
              <Bot className="h-4 w-4" />
              查看进度
            </button>
          )}
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <UserPlus className="h-4 w-4" />
            手动添加
          </button>
        </div>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
          <h3 className="mb-4 text-lg font-semibold">手动添加导师</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(['name', 'university', 'email', 'department', 'homepage', 'region'] as const).map((field) => (
              <div key={field}>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {{name:'姓名*',university:'学校*',email:'邮箱（可选，自动补全）',department:'院系',homepage:'主页',region:'地区'}[field]}
                </label>
                <input
                  type="text"
                  value={(form as any)[field]}
                  onChange={(e) => setForm({ ...form, [field]: e.target.value })}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                  placeholder={field === 'region' ? 'China / US / UK ...' : ''}
                />
              </div>
            ))}
            <div className="sm:col-span-2 lg:col-span-3">
              <label className="block text-sm font-medium text-gray-700 mb-1">研究方向</label>
              <input
                type="text"
                value={form.research_summary}
                onChange={(e) => setForm({ ...form, research_summary: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>
          <div className="mt-4 flex gap-3">
            <button onClick={handleAdd} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">添加</button>
            <button onClick={() => setShowAdd(false)} className="rounded-lg border px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">取消</button>
          </div>
        </div>
      )}

      {/* Grouped professor list */}
      {loading ? (
        <div className="flex items-center justify-center p-12">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
        </div>
      ) : professors.length === 0 ? (
        <div className="rounded-xl bg-white p-16 text-center shadow-sm border border-gray-100">
          <Globe className="mx-auto h-16 w-16 text-gray-200" />
          <p className="mt-4 text-gray-500">暂无导师数据</p>
          <p className="mt-1 text-sm text-gray-400">点击"Agent 搜索"让 AI 自动查找导师</p>
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.map(([region, uniMap]) => {
            const collapsed = collapsedRegions.has(region)
            const profCount = Object.values(uniMap).reduce((s, arr) => s + arr.length, 0)
            const uniCount = Object.keys(uniMap).length
            const gradient = regionColors[region] || 'from-gray-500 to-gray-600'

            return (
              <div key={region} className="rounded-xl bg-white shadow-sm border border-gray-100 overflow-hidden">
                {/* Region header */}
                <button
                  onClick={() => toggleRegion(region)}
                  className="w-full flex items-center gap-3 px-5 py-4 hover:bg-gray-50 transition-colors"
                >
                  <div className={`flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br ${gradient} text-white`}>
                    <MapPin className="h-4 w-4" />
                  </div>
                  <div className="text-left flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-900">
                      {REGION_LABELS[region] || region}
                    </p>
                    <p className="text-xs text-gray-500">
                      {uniCount} 所学校 · {profCount} 位导师
                    </p>
                  </div>
                  {collapsed ? <ChevronRight className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
                </button>

                {!collapsed && (
                  <div className="border-t border-gray-100">
                    {Object.entries(uniMap)
                      .sort(([, a], [, b]) => b.length - a.length)
                      .map(([uni, profs]) => (
                        <div key={uni} className="border-b border-gray-50 last:border-b-0">
                          {/* University sub-header */}
                          <div className="flex items-center gap-2 px-5 py-2.5 bg-gray-50/50">
                            <Building2 className="h-3.5 w-3.5 text-gray-400" />
                            <span className="text-xs font-medium text-gray-600">{uni}</span>
                            <span className="text-xs text-gray-400">({profs.length})</span>
                          </div>

                          {/* Professor cards */}
                          <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
                            {profs.map((p: any) => {
                              const es = emailStatus(p.id)
                              return (
                                <div
                                  key={p.id}
                                  onClick={() => setSelectedProf(p)}
                                  className="group relative flex items-start gap-3 rounded-xl border border-gray-200 p-4 cursor-pointer hover:border-indigo-300 hover:shadow-md transition-all"
                                >
                                  {/* Star button */}
                                  <button
                                    onClick={(e) => handleToggleStar(e, p.id)}
                                    className="absolute top-2 left-2 rounded-md p-1 transition-all"
                                  >
                                    <Star className={`h-4 w-4 ${p.is_starred ? 'fill-yellow-400 text-yellow-400' : 'text-gray-300 opacity-0 group-hover:opacity-100 hover:text-yellow-400'}`} />
                                  </button>
                                  {/* Avatar */}
                                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-400 to-purple-500 text-sm font-bold text-white">
                                    {initials(p.name)}
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-2">
                                      <p className="text-sm font-semibold text-gray-900 truncate">{p.name}</p>
                                      {p.homepage && (
                                        <a
                                          href={p.homepage}
                                          target="_blank"
                                          rel="noreferrer"
                                          onClick={(e) => e.stopPropagation()}
                                          className="text-gray-400 hover:text-indigo-500"
                                        >
                                          <ExternalLink className="h-3 w-3" />
                                        </a>
                                      )}
                                    </div>
                                    {p.research_summary && (
                                      <p className="mt-0.5 text-xs text-gray-500 line-clamp-2">{p.research_summary}</p>
                                    )}
                                    {/* Tags */}
                                    {(() => {
                                      const tags = parseTags(p.tags)
                                      return tags.length > 0 ? (
                                        <div className="mt-1.5 flex flex-wrap gap-1">
                                          {tags.map((tag: string) => {
                                            const preset = PRESET_TAGS[tag]
                                            return (
                                              <span
                                                key={tag}
                                                className={`inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${
                                                  preset ? preset.color : 'bg-gray-100 text-gray-600 border-gray-200'
                                                }`}
                                              >
                                                {preset ? preset.label : tag}
                                                <button
                                                  onClick={(e) => handleRemoveTag(e, p.id, tag)}
                                                  className="ml-0.5 rounded-full hover:bg-black/10 p-0.5"
                                                >
                                                  <X className="h-2 w-2" />
                                                </button>
                                              </span>
                                            )
                                          })}
                                        </div>
                                      ) : null
                                    })()}
                                    {/* Status badges */}
                                    <div className="mt-1.5 flex flex-wrap gap-1.5 items-center">
                                      {newProfIds.has(p.id) && (
                                        <span className="inline-flex items-center rounded-full bg-indigo-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                                          新
                                        </span>
                                      )}
                                      {es === 'sent' && (
                                        <span className="inline-flex items-center gap-0.5 rounded-full bg-green-50 px-2 py-0.5 text-[10px] font-medium text-green-600">
                                          <Send className="h-2.5 w-2.5" /> 已发送
                                        </span>
                                      )}
                                      {es === 'draft' && (
                                        <span className="inline-flex items-center gap-0.5 rounded-full bg-yellow-50 px-2 py-0.5 text-[10px] font-medium text-yellow-600">
                                          <FileText className="h-2.5 w-2.5" /> 草稿
                                        </span>
                                      )}
                                      {!es && (
                                        <span className="inline-flex items-center gap-0.5 rounded-full bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-gray-400">
                                          <Mail className="h-2.5 w-2.5" /> 未生成
                                        </span>
                                      )}
                                      {/* Add tag button */}
                                      <div className="relative">
                                        <button
                                          onClick={(e) => { e.stopPropagation(); setTagPickerProf(tagPickerProf === p.id ? null : p.id) }}
                                          className="inline-flex items-center gap-0.5 rounded-full border border-dashed border-gray-300 px-1.5 py-0.5 text-[10px] text-gray-400 hover:border-indigo-400 hover:text-indigo-500 transition-colors"
                                        >
                                          <Tag className="h-2.5 w-2.5" />
                                          <Plus className="h-2 w-2" />
                                        </button>
                                        {/* Tag picker dropdown */}
                                        {tagPickerProf === p.id && (
                                          <div
                                            className="absolute left-0 top-full mt-1 z-50 w-36 rounded-lg bg-white border border-gray-200 shadow-lg py-1"
                                            onClick={(e) => e.stopPropagation()}
                                          >
                                            {Object.entries(PRESET_TAGS)
                                              .filter(([key]) => !parseTags(p.tags).includes(key))
                                              .map(([key, { label, color }]) => (
                                                <button
                                                  key={key}
                                                  onClick={(e) => handleAddTag(e, p.id, key)}
                                                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-50 transition-colors"
                                                >
                                                  <span className={`inline-block rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${color}`}>{label}</span>
                                                </button>
                                              ))}
                                            {Object.keys(PRESET_TAGS).every((key) => parseTags(p.tags).includes(key)) && (
                                              <p className="px-3 py-1.5 text-[10px] text-gray-400">所有标签已添加</p>
                                            )}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                  {/* Enrich button */}
                                  {enrichingIds.has(p.id) ? (
                                    <div className="absolute top-2 right-9 rounded-md p-1">
                                      <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />
                                    </div>
                                  ) : (
                                    <button
                                      onClick={(e) => handleEnrich(e, p.id)}
                                      title="搜索补全信息"
                                      className="absolute top-2 right-9 rounded-md p-1 text-gray-300 opacity-0 group-hover:opacity-100 hover:text-indigo-500 hover:bg-indigo-50 transition-all"
                                    >
                                      <RefreshCw className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                  {/* Delete button */}
                                  <button
                                    onClick={(e) => handleDelete(e, p.id)}
                                    className="absolute top-2 right-2 rounded-md p-1 text-gray-300 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-50 transition-all"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Professor detail modal */}
      <ProfessorDetail
        professor={selectedProf}
        onClose={() => { setSelectedProf(null); fetchData() }}
        onUpdate={() => {
          fetchData()
          // Refresh selectedProf with latest data
          if (selectedProf) {
            getProfessors().then((res) => {
              const updated = res.data.find((p: any) => p.id === selectedProf.id)
              if (updated) setSelectedProf(updated)
            })
          }
        }}
        wsMessages={wsMessages}
      />
    </div>
  )
}
