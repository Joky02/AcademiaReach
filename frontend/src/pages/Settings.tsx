import { useState, useEffect, useRef } from 'react'
import {
  Save, Loader2, CheckCircle2, Upload, X, Plus, FileText,
  Mail, Shield, AlertCircle, Eye, EyeOff, Sparkles, Cpu, Code, Ban,
} from 'lucide-react'
import {
  getProfile, updateProfile, generateProfile, getSettings, updateLlmConfig,
  getCvStatus, uploadCv, uploadTranscript, uploadPaper, deletePaper,
  updateKeywords,
  getEmailConfig, verifyEmail,
  getPrompts, updatePrompts,
  getPromptTemplates, updatePromptTemplate,
  getBlacklist, removeFromBlacklist,
} from '../services/api'

type LlmProvider = 'openai' | 'deepseek' | 'ollama'

export default function SettingsPage() {
  const [profile, setProfile] = useState('')
  const [settings, setSettings] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  // Profile 保存
  const [savingProfile, setSavingProfile] = useState(false)
  const [savedProfile, setSavedProfile] = useState(false)

  // Profile AI 生成
  const [genModalOpen, setGenModalOpen] = useState(false)
  const [genPitch, setGenPitch] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)

  // 搜索关键词编辑
  const [keywords, setKeywords] = useState<string[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [newKw, setNewKw] = useState('')
  const [newRegion, setNewRegion] = useState('')
  const [serperKey, setSerperKey] = useState('')
  const [showSerperKey, setShowSerperKey] = useState(false)
  const [savingKw, setSavingKw] = useState(false)
  const [savedKw, setSavedKw] = useState(false)

  // 附件（简历 / 成绩单 / 论文）
  const [cvStatus, setCvStatus] = useState<any>(null)
  const [uploading, setUploading] = useState<string | null>(null)
  const cnFileRef = useRef<HTMLInputElement>(null)
  const enFileRef = useRef<HTMLInputElement>(null)
  const tCnFileRef = useRef<HTMLInputElement>(null)
  const tEnFileRef = useRef<HTMLInputElement>(null)
  const paperFileRef = useRef<HTMLInputElement>(null)

  // 自定义 Prompt
  const [promptForm, setPromptForm] = useState({
    search_preference: '',
    compose_style_cn: '',
    compose_style_en: '',
    compose_extra_cn: '',
    compose_extra_en: '',
  })
  const [savingPrompt, setSavingPrompt] = useState(false)
  const [savedPrompt, setSavedPrompt] = useState(false)

  // LLM 后端配置
  const [llmProvider, setLlmProvider] = useState<LlmProvider>('openai')
  const [llmForm, setLlmForm] = useState({
    openai: { model: '', base_url: '', api_key: '', api_key_set: false },
    deepseek: { model: '', base_url: '', api_key: '', api_key_set: false },
    ollama: { model: '', base_url: '' },
  })
  const [showLlmKey, setShowLlmKey] = useState(false)
  const [savingLlm, setSavingLlm] = useState(false)
  const [savedLlm, setSavedLlm] = useState(false)

  // Prompt 模板编辑（backend/prompts/*.md）
  type PromptTpl = { name: string; description: string; content: string }
  const [promptTpls, setPromptTpls] = useState<PromptTpl[]>([])
  const [activeTpl, setActiveTpl] = useState<string>('')
  const [tplDraft, setTplDraft] = useState<string>('')
  const [savingTpl, setSavingTpl] = useState(false)
  const [savedTpl, setSavedTpl] = useState(false)

  // 黑名单
  type BlacklistEntry = { id: number; name: string; university: string; reason?: string; created_at: string }
  const [blacklist, setBlacklist] = useState<BlacklistEntry[]>([])
  const [removingBlId, setRemovingBlId] = useState<number | null>(null)

  // 邮箱验证
  const [emailForm, setEmailForm] = useState({
    smtp_host: '', smtp_port: 587, smtp_username: '', smtp_password: '', smtp_use_tls: true,
    imap_host: '', imap_port: 993, imap_username: '', imap_password: '', imap_use_ssl: true,
  })
  const [showSmtpPwd, setShowSmtpPwd] = useState(false)
  const [showImapPwd, setShowImapPwd] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [verifyResult, setVerifyResult] = useState<any>(null)

  const fetchAll = () => {
    Promise.all([getProfile(), getSettings(), getCvStatus(), getEmailConfig(), getPrompts(), getPromptTemplates(), getBlacklist()])
      .then(([profRes, setRes, cvRes, emailRes, promptRes, tplRes, blRes]) => {
        setProfile(profRes.data.content)
        setSettings(setRes.data)
        setKeywords(setRes.data.search?.keywords || [])
        setRegions(setRes.data.search?.regions || [])
        const llm = setRes.data.llm || {}
        setLlmProvider((llm.provider as LlmProvider) || 'openai')
        setLlmForm({
          openai: {
            model: llm.openai?.model || '',
            base_url: llm.openai?.base_url || 'https://api.openai.com/v1',
            api_key: '',
            api_key_set: !!llm.openai?.api_key_set,
          },
          deepseek: {
            model: llm.deepseek?.model || 'deepseek-chat',
            base_url: llm.deepseek?.base_url || 'https://api.deepseek.com/v1',
            api_key: '',
            api_key_set: !!llm.deepseek?.api_key_set,
          },
          ollama: {
            model: llm.ollama?.model || 'llama3',
            base_url: llm.ollama?.base_url || 'http://localhost:11434',
          },
        })
        setCvStatus(cvRes.data)
        const s = emailRes.data.smtp
        const im = emailRes.data.imap
        setEmailForm((prev) => ({
          ...prev,
          smtp_host: s.host, smtp_port: s.port, smtp_username: s.username, smtp_use_tls: s.use_tls,
          imap_host: im.host, imap_port: im.port, imap_username: im.username, imap_use_ssl: im.use_ssl,
        }))
        setPromptForm(promptRes.data)
        const tpls = (tplRes.data || []) as PromptTpl[]
        setPromptTpls(tpls)
        if (tpls.length > 0) {
          setActiveTpl(tpls[0].name)
          setTplDraft(tpls[0].content)
        }
        setBlacklist(blRes.data || [])
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchAll() }, [])

  // ── Profile AI 生成 ──
  const handleGenerateProfile = async () => {
    // 已有非空 profile 时确认覆盖
    if (profile.trim() && !confirm('当前 Profile 不是空的，AI 生成的内容会替换 textarea 里的内容（不会自动保存，你可以再编辑再点保存）。继续？')) {
      return
    }
    setGenerating(true)
    setGenError(null)
    try {
      const res = await generateProfile(genPitch.trim() || undefined)
      setProfile(res.data.content || '')
      setGenModalOpen(false)
      setGenPitch('')
    } catch (e: any) {
      setGenError(e.response?.data?.detail || e.message || '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  // ── Profile 保存 ──
  const handleSaveProfile = async () => {
    setSavingProfile(true)
    try {
      await updateProfile(profile)
      setSavedProfile(true)
      setTimeout(() => setSavedProfile(false), 2000)
    } finally {
      setSavingProfile(false)
    }
  }

  // ── 关键词保存 ──
  const handleAddKeyword = () => {
    const kw = newKw.trim()
    if (kw && !keywords.includes(kw)) {
      setKeywords([...keywords, kw])
    }
    setNewKw('')
  }

  const handleAddRegion = () => {
    const r = newRegion.trim()
    if (r && !regions.includes(r)) {
      setRegions([...regions, r])
    }
    setNewRegion('')
  }

  const handleSaveKeywords = async () => {
    setSavingKw(true)
    try {
      const res = await updateKeywords(keywords, regions, serperKey.trim() || undefined)
      setSerperKey('')
      setSettings((prev: any) => ({
        ...prev,
        search: {
          ...prev?.search,
          keywords,
          regions,
          serper_api_key_set: Boolean(res.data?.serper_api_key_set),
        },
      }))
      setSavedKw(true)
      setTimeout(() => setSavedKw(false), 2000)
    } finally {
      setSavingKw(false)
    }
  }

  // ── 黑名单移除 ──
  const handleRemoveBlacklist = async (id: number) => {
    setRemovingBlId(id)
    try {
      await removeFromBlacklist(id)
      setBlacklist(blacklist.filter((b) => b.id !== id))
    } finally {
      setRemovingBlId(null)
    }
  }

  // ── Prompt 模板编辑 ──
  const handleSwitchTpl = (name: string) => {
    setActiveTpl(name)
    const tpl = promptTpls.find((t) => t.name === name)
    setTplDraft(tpl?.content || '')
    setSavedTpl(false)
  }

  const handleSaveTpl = async () => {
    if (!activeTpl) return
    setSavingTpl(true)
    try {
      await updatePromptTemplate(activeTpl, tplDraft)
      setPromptTpls(promptTpls.map((t) => (t.name === activeTpl ? { ...t, content: tplDraft } : t)))
      setSavedTpl(true)
      setTimeout(() => setSavedTpl(false), 2000)
    } finally {
      setSavingTpl(false)
    }
  }

  const activeTplMeta = promptTpls.find((t) => t.name === activeTpl)

  // ── LLM 后端配置保存 ──
  const handleSaveLlm = async () => {
    setSavingLlm(true)
    try {
      const payload: any = { provider: llmProvider }
      if (llmProvider === 'ollama') {
        payload.ollama = { model: llmForm.ollama.model, base_url: llmForm.ollama.base_url }
      } else {
        const sub = llmForm[llmProvider]
        payload[llmProvider] = {
          model: sub.model,
          base_url: sub.base_url,
          api_key: sub.api_key,  // 空字符串后端会保留旧值
        }
      }
      await updateLlmConfig(payload)
      setSavedLlm(true)
      // 刷新顶部状态卡片 & 清空 api_key 输入框、标记已配置
      const res = await getSettings()
      setSettings(res.data)
      const llm = res.data.llm || {}
      setLlmForm((prev) => ({
        ...prev,
        openai: { ...prev.openai, api_key: '', api_key_set: !!llm.openai?.api_key_set },
        deepseek: { ...prev.deepseek, api_key: '', api_key_set: !!llm.deepseek?.api_key_set },
      }))
      setTimeout(() => setSavedLlm(false), 2000)
    } finally {
      setSavingLlm(false)
    }
  }

  // ── 自定义 Prompt 保存 ──
  const handleSavePrompts = async () => {
    setSavingPrompt(true)
    try {
      await updatePrompts(promptForm)
      setSavedPrompt(true)
      setTimeout(() => setSavedPrompt(false), 2000)
    } finally {
      setSavingPrompt(false)
    }
  }

  // ── 附件上传 ──
  const refreshAttachments = async () => {
    const res = await getCvStatus()
    setCvStatus(res.data)
  }

  const handleCvUpload = async (lang: 'cn' | 'en', file: File | undefined) => {
    if (!file) return
    setUploading(`cv-${lang}`)
    try {
      await uploadCv(lang, file)
      await refreshAttachments()
    } finally {
      setUploading(null)
    }
  }

  const handleTranscriptUpload = async (lang: 'cn' | 'en', file: File | undefined) => {
    if (!file) return
    setUploading(`transcript-${lang}`)
    try {
      await uploadTranscript(lang, file)
      await refreshAttachments()
    } finally {
      setUploading(null)
    }
  }

  const handlePaperUpload = async (file: File | undefined) => {
    if (!file) return
    setUploading(`paper:${file.name}`)
    try {
      await uploadPaper(file)
      await refreshAttachments()
    } finally {
      setUploading(null)
      if (paperFileRef.current) paperFileRef.current.value = ''
    }
  }

  const handlePaperDelete = async (name: string) => {
    if (!confirm(`确定删除论文 "${name}" 吗？`)) return
    setUploading(`paper-del:${name}`)
    try {
      await deletePaper(name)
      await refreshAttachments()
    } finally {
      setUploading(null)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">设置</h2>

      {/* 系统配置状态 */}
      {settings && (
        <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
          <h3 className="mb-4 text-lg font-semibold text-gray-800">系统配置状态</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm text-gray-500">LLM 后端</p>
              <p className="mt-1 font-medium text-gray-900">{settings.llm?.provider || 'N/A'}</p>
            </div>
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm text-gray-500">Serper 搜索</p>
              <p className="mt-1 font-medium">
                {settings.search?.serper_api_key_set ? (
                  <span className="text-green-600">已配置</span>
                ) : (
                  <span className="text-red-500">未配置</span>
                )}
              </p>
            </div>
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm text-gray-500">SMTP 发件</p>
              <p className="mt-1 font-medium">
                {settings.smtp?.configured ? (
                  <span className="text-green-600">已配置</span>
                ) : (
                  <span className="text-red-500">未配置</span>
                )}
              </p>
              {settings.smtp?.username && (
                <p className="text-xs text-gray-400 mt-1">{settings.smtp.username}</p>
              )}
            </div>
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm text-gray-500">IMAP 收件</p>
              <p className="mt-1 font-medium">
                {settings.imap?.configured ? (
                  <span className="text-green-600">已配置</span>
                ) : (
                  <span className="text-red-500">未配置</span>
                )}
              </p>
            </div>
          </div>
          <p className="mt-4 text-sm text-gray-400">
            API Key 和邮箱均可在下方配置；已保存的敏感字段不会回显到浏览器。
          </p>
        </div>
      )}

      {/* LLM 后端配置 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-indigo-500" />
            <h3 className="text-lg font-semibold text-gray-800">LLM 后端配置</h3>
          </div>
          <button
            onClick={handleSaveLlm}
            disabled={savingLlm}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {savingLlm ? <Loader2 className="h-4 w-4 animate-spin" /> : savedLlm ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {savingLlm ? '保存中...' : savedLlm ? '已保存' : '保存'}
          </button>
        </div>

        <div className="mb-5">
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Provider</label>
          <p className="text-xs text-gray-400 mb-2">切换搜索 / 邮件生成 Agent 使用的 LLM 后端</p>
          <div className="flex gap-2">
            {(['openai', 'deepseek', 'ollama'] as LlmProvider[]).map((p) => (
              <button
                key={p}
                onClick={() => setLlmProvider(p)}
                className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                  llmProvider === p
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {p === 'openai' ? 'OpenAI 兼容' : p === 'deepseek' ? 'DeepSeek' : 'Ollama (本地)'}
              </button>
            ))}
          </div>
        </div>

        {llmProvider !== 'ollama' && (
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Model</label>
              <input
                value={llmForm[llmProvider].model}
                onChange={(e) => setLlmForm({
                  ...llmForm,
                  [llmProvider]: { ...llmForm[llmProvider], model: e.target.value },
                })}
                placeholder={llmProvider === 'deepseek' ? 'deepseek-chat / deepseek-reasoner' : 'gpt-4o'}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Base URL</label>
              <input
                value={llmForm[llmProvider].base_url}
                onChange={(e) => setLlmForm({
                  ...llmForm,
                  [llmProvider]: { ...llmForm[llmProvider], base_url: e.target.value },
                })}
                placeholder={llmProvider === 'deepseek' ? 'https://api.deepseek.com/v1' : 'https://api.openai.com/v1'}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">API Key</label>
              <div className="relative">
                <input
                  type={showLlmKey ? 'text' : 'password'}
                  value={llmForm[llmProvider].api_key}
                  onChange={(e) => setLlmForm({
                    ...llmForm,
                    [llmProvider]: { ...llmForm[llmProvider], api_key: e.target.value },
                  })}
                  placeholder={llmForm[llmProvider].api_key_set ? '已配置（留空则保留原 Key）' : 'sk-...'}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                />
                <button onClick={() => setShowLlmKey(!showLlmKey)} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showLlmKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </div>
        )}

        {llmProvider === 'ollama' && (
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Model</label>
              <input
                value={llmForm.ollama.model}
                onChange={(e) => setLlmForm({ ...llmForm, ollama: { ...llmForm.ollama, model: e.target.value } })}
                placeholder="llama3 / qwen2.5 / ..."
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Base URL</label>
              <input
                value={llmForm.ollama.base_url}
                onChange={(e) => setLlmForm({ ...llmForm, ollama: { ...llmForm.ollama, base_url: e.target.value } })}
                placeholder="http://localhost:11434"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <p className="text-xs text-gray-400">Ollama 本地模型不需要 API Key</p>
          </div>
        )}
      </div>

      {/* 邮箱验证 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Mail className="h-5 w-5 text-indigo-500" />
            <h3 className="text-lg font-semibold text-gray-800">邮箱配置与验证</h3>
          </div>
          <button
            onClick={async () => {
              setVerifying(true)
              setVerifyResult(null)
              try {
                const res = await verifyEmail({ ...emailForm, save: true })
                setVerifyResult(res.data)
              } catch (e: any) {
                setVerifyResult({ smtp: { ok: false, message: '请求失败' }, imap: { ok: false, message: '请求失败' } })
              } finally {
                setVerifying(false)
              }
            }}
            disabled={verifying || !emailForm.smtp_host || !emailForm.smtp_username || !emailForm.smtp_password}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {verifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
            {verifying ? '验证中...' : '验证并保存'}
          </button>
        </div>

        {/* 验证结果 */}
        {verifyResult && (
          <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className={`flex items-center gap-2 rounded-lg p-3 text-sm ${
              verifyResult.smtp?.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
            }`}>
              {verifyResult.smtp?.ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
              {verifyResult.smtp?.message}
            </div>
            <div className={`flex items-center gap-2 rounded-lg p-3 text-sm ${
              verifyResult.imap?.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
            }`}>
              {verifyResult.imap?.ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
              {verifyResult.imap?.message}
            </div>
            {verifyResult.saved && (
              <div className="sm:col-span-2 flex items-center gap-2 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">
                <CheckCircle2 className="h-4 w-4" /> 配置已保存到 config.yaml
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* SMTP */}
          <div>
            <p className="text-sm font-medium text-gray-700 mb-3">SMTP 发件服务器</p>
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2">
                  <label className="block text-xs text-gray-500 mb-1">服务器地址</label>
                  <input value={emailForm.smtp_host} onChange={(e) => setEmailForm({ ...emailForm, smtp_host: e.target.value })}
                    placeholder="smtp.example.com" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">端口</label>
                  <input type="number" value={emailForm.smtp_port} onChange={(e) => setEmailForm({ ...emailForm, smtp_port: parseInt(e.target.value) || 587 })}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
                </div>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">邮箱账号</label>
                <input value={emailForm.smtp_username} onChange={(e) => setEmailForm({ ...emailForm, smtp_username: e.target.value })}
                  placeholder="you@example.com" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">密码 / 授权码</label>
                <div className="relative">
                  <input type={showSmtpPwd ? 'text' : 'password'} value={emailForm.smtp_password}
                    onChange={(e) => setEmailForm({ ...emailForm, smtp_password: e.target.value })}
                    placeholder="输入密码或授权码"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
                  <button onClick={() => setShowSmtpPwd(!showSmtpPwd)} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                    {showSmtpPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-600">
                <input type="checkbox" checked={emailForm.smtp_use_tls} onChange={(e) => setEmailForm({ ...emailForm, smtp_use_tls: e.target.checked })}
                  className="rounded border-gray-300 text-indigo-600" />
                使用 STARTTLS
              </label>
            </div>
          </div>

          {/* IMAP */}
          <div>
            <p className="text-sm font-medium text-gray-700 mb-3">IMAP 收件服务器</p>
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2">
                  <label className="block text-xs text-gray-500 mb-1">服务器地址</label>
                  <input value={emailForm.imap_host} onChange={(e) => setEmailForm({ ...emailForm, imap_host: e.target.value })}
                    placeholder="imap.example.com" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">端口</label>
                  <input type="number" value={emailForm.imap_port} onChange={(e) => setEmailForm({ ...emailForm, imap_port: parseInt(e.target.value) || 993 })}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
                </div>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">邮箱账号</label>
                <input value={emailForm.imap_username} onChange={(e) => setEmailForm({ ...emailForm, imap_username: e.target.value })}
                  placeholder="you@example.com" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">密码 / 授权码</label>
                <div className="relative">
                  <input type={showImapPwd ? 'text' : 'password'} value={emailForm.imap_password}
                    onChange={(e) => setEmailForm({ ...emailForm, imap_password: e.target.value })}
                    placeholder="输入密码或授权码"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500" />
                  <button onClick={() => setShowImapPwd(!showImapPwd)} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                    {showImapPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-600">
                <input type="checkbox" checked={emailForm.imap_use_ssl} onChange={(e) => setEmailForm({ ...emailForm, imap_use_ssl: e.target.checked })}
                  className="rounded border-gray-300 text-indigo-600" />
                使用 SSL
              </label>
            </div>
          </div>
        </div>
        <p className="mt-4 text-xs text-gray-400">点击「验证并保存」会同时测试 SMTP/IMAP 连接，验证通过后自动保存到 config.yaml</p>
      </div>

      {/* 搜索关键词编辑 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">搜索关键词 & 地区</h3>
          <button
            onClick={handleSaveKeywords}
            disabled={savingKw}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {savingKw ? <Loader2 className="h-4 w-4 animate-spin" /> : savedKw ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {savingKw ? '保存中...' : savedKw ? '已保存' : '保存'}
          </button>
        </div>

        <div className="mb-5">
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Serper API Key</label>
          <p className="text-xs text-gray-400 mb-2">
            用于 Google 搜索。{settings?.search?.serper_api_key_set ? '已配置，留空会保留当前 Key。' : '当前尚未配置。'}
          </p>
          <div className="relative">
            <input
              type={showSerperKey ? 'text' : 'password'}
              autoComplete="new-password"
              value={serperKey}
              onChange={(e) => setSerperKey(e.target.value)}
              placeholder={settings?.search?.serper_api_key_set ? '输入新 Key 以替换当前配置' : '输入 Serper API Key'}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
            <button
              onClick={() => setShowSerperKey(!showSerperKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title={showSerperKey ? '隐藏 API Key' : '显示 API Key'}
            >
              {showSerperKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {/* 关键词 */}
        <p className="text-sm text-gray-500 mb-2">研究方向关键词（用于自动搜索导师）</p>
        <div className="flex flex-wrap gap-2 mb-3">
          {keywords.map((kw) => (
            <span key={kw} className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-3 py-1 text-sm text-indigo-700">
              {kw}
              <button onClick={() => setKeywords(keywords.filter((k) => k !== kw))} className="text-indigo-400 hover:text-indigo-700">
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2 mb-5">
          <input
            value={newKw}
            onChange={(e) => setNewKw(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddKeyword()}
            placeholder="输入关键词，回车添加"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          />
          <button onClick={handleAddKeyword} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">
            <Plus className="h-4 w-4" />
          </button>
        </div>

        {/* 地区 */}
        <p className="text-sm text-gray-500 mb-2">目标地区（China 地区导师将使用中文邮件 + 中文简历）</p>
        <div className="flex flex-wrap gap-2 mb-3">
          {regions.map((r) => (
            <span key={r} className="inline-flex items-center gap-1 rounded-full bg-green-50 px-3 py-1 text-sm text-green-700">
              {r}
              <button onClick={() => setRegions(regions.filter((x) => x !== r))} className="text-green-400 hover:text-green-700">
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={newRegion}
            onChange={(e) => setNewRegion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddRegion()}
            placeholder="如 US, UK, China, Singapore..."
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          />
          <button onClick={handleAddRegion} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* 自定义 Prompt */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-purple-500" />
            <h3 className="text-lg font-semibold text-gray-800">Agent 行为自定义</h3>
          </div>
          <button
            onClick={handleSavePrompts}
            disabled={savingPrompt}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {savingPrompt ? <Loader2 className="h-4 w-4 animate-spin" /> : savedPrompt ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {savingPrompt ? '保存中...' : savedPrompt ? '已保存' : '保存'}
          </button>
        </div>
        <p className="text-sm text-gray-500 mb-5">自定义搜索和邮件生成 Agent 的行为偏好，这些内容会注入到 Agent 的 System Prompt 中</p>

        {/* 搜索偏好 */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-1.5">🔍 搜索偏好</label>
          <p className="text-xs text-gray-400 mb-2">告诉搜索 Agent 你想找什么样的导师，比如偏好哪些学校、研究方向、招生状态等</p>
          <textarea
            value={promptForm.search_preference}
            onChange={(e) => setPromptForm({ ...promptForm, search_preference: e.target.value })}
            rows={3}
            placeholder="例如：优先找近两年有活跃论文发表的导师，偏好 top 学校，关注组合优化和 LLM for optimization 方向"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* 中文邮件风格 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">✉️ 中文邮件风格</label>
            <p className="text-xs text-gray-400 mb-2">给国内导师写信时的风格要求</p>
            <textarea
              value={promptForm.compose_style_cn}
              onChange={(e) => setPromptForm({ ...promptForm, compose_style_cn: e.target.value })}
              rows={3}
              placeholder="例如：语气自然真诚，像同行之间交流。提到我和导师研究方向的具体交集。"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* 英文邮件风格 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">✉️ English Email Style</label>
            <p className="text-xs text-gray-400 mb-2">给海外导师写信时的风格要求</p>
            <textarea
              value={promptForm.compose_style_en}
              onChange={(e) => setPromptForm({ ...promptForm, compose_style_en: e.target.value })}
              rows={3}
              placeholder="e.g., Be direct and specific. Mention a concrete connection between my work and the professor's research."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* 中文额外要求 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">📝 中文邮件额外要求</label>
            <p className="text-xs text-gray-400 mb-2">需要在中文邮件中额外强调或避免的内容</p>
            <textarea
              value={promptForm.compose_extra_cn}
              onChange={(e) => setPromptForm({ ...promptForm, compose_extra_cn: e.target.value })}
              rows={3}
              placeholder="例如：结尾提到我可以提供代码仓库链接；不要提到竞赛经历"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* 英文额外要求 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">📝 English Extra Instructions</label>
            <p className="text-xs text-gray-400 mb-2">Additional things to include or avoid in English emails</p>
            <textarea
              value={promptForm.compose_extra_en}
              onChange={(e) => setPromptForm({ ...promptForm, compose_extra_en: e.target.value })}
              rows={3}
              placeholder="e.g., Mention my ICPC gold medal; Don't mention GPA"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>
        </div>
      </div>

      {/* Prompt 模板编辑器 — 直接编辑 backend/prompts/*.md */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Code className="h-5 w-5 text-indigo-500" />
            <h3 className="text-lg font-semibold text-gray-800">Prompt 模板</h3>
          </div>
          <button
            onClick={handleSaveTpl}
            disabled={savingTpl || !activeTpl}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {savingTpl ? <Loader2 className="h-4 w-4 animate-spin" /> : savedTpl ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {savingTpl ? '保存中...' : savedTpl ? '已保存' : '保存'}
          </button>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          直接编辑 <code className="rounded bg-gray-100 px-1 py-0.5">backend/prompts/*.md</code> 中的 system prompt。修改后立即生效（每次调用都从磁盘读取，无需重启服务）。
        </p>

        <div className="flex flex-wrap gap-2 mb-3">
          {promptTpls.map((t) => (
            <button
              key={t.name}
              onClick={() => handleSwitchTpl(t.name)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTpl === t.name
                  ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                  : 'border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>

        {activeTplMeta && (
          <p className="text-xs text-gray-400 mb-2">{activeTplMeta.description}</p>
        )}

        <textarea
          value={tplDraft}
          onChange={(e) => setTplDraft(e.target.value)}
          rows={20}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          placeholder="选择上方模板进行编辑..."
        />

        {activeTpl === 'search_system' && (
          <p className="mt-2 text-xs text-amber-600">
            ⚠️ 此模板含 <code className="rounded bg-amber-50 px-1">{'{extra}'}</code> 占位符（运行时替换为关键词/地区/搜索偏好）。删除占位符会导致这些用户配置无法注入。
          </p>
        )}
      </div>

      {/* 邮件附件：简历 / 成绩单 / 论文 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <h3 className="mb-2 text-lg font-semibold text-gray-800">邮件附件</h3>
        <p className="mb-4 text-sm text-gray-500">
          发送邮件时附件清单 = 简历 + 成绩单（按导师所在地区自动选中/英）+ <code className="rounded bg-gray-100 px-1">papers/</code> 目录下所有论文。
        </p>

        {/* 简历 */}
        <p className="text-sm font-medium text-gray-700 mb-2">简历（按导师地区自动选择）</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 mb-5">
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-5 text-center hover:border-indigo-300 transition-colors">
            <FileText className="mx-auto h-8 w-8 text-gray-400" />
            <p className="mt-2 text-sm font-medium text-gray-700">中文简历</p>
            {cvStatus?.cv?.cn?.uploaded ? (
              <p className="text-xs text-green-600 mt-1">✓ {cvStatus.cv.cn.name} ({formatSize(cvStatus.cv.cn.size)})</p>
            ) : (
              <p className="text-xs text-gray-400 mt-1">未上传</p>
            )}
            <input ref={cnFileRef} type="file" accept=".pdf" className="hidden" onChange={(e) => handleCvUpload('cn', e.target.files?.[0])} />
            <button
              onClick={() => cnFileRef.current?.click()}
              disabled={uploading === 'cv-cn'}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
            >
              {uploading === 'cv-cn' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {cvStatus?.cv?.cn?.uploaded ? '重新上传' : '上传 PDF'}
            </button>
          </div>
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-5 text-center hover:border-indigo-300 transition-colors">
            <FileText className="mx-auto h-8 w-8 text-gray-400" />
            <p className="mt-2 text-sm font-medium text-gray-700">英文简历 (English CV)</p>
            {cvStatus?.cv?.en?.uploaded ? (
              <p className="text-xs text-green-600 mt-1">✓ {cvStatus.cv.en.name} ({formatSize(cvStatus.cv.en.size)})</p>
            ) : (
              <p className="text-xs text-gray-400 mt-1">未上传</p>
            )}
            <input ref={enFileRef} type="file" accept=".pdf" className="hidden" onChange={(e) => handleCvUpload('en', e.target.files?.[0])} />
            <button
              onClick={() => enFileRef.current?.click()}
              disabled={uploading === 'cv-en'}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
            >
              {uploading === 'cv-en' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {cvStatus?.cv?.en?.uploaded ? '重新上传' : '上传 PDF'}
            </button>
          </div>
        </div>

        {/* 成绩单 */}
        <p className="text-sm font-medium text-gray-700 mb-2">成绩单（按导师地区自动选择）</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 mb-5">
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-5 text-center hover:border-indigo-300 transition-colors">
            <FileText className="mx-auto h-8 w-8 text-gray-400" />
            <p className="mt-2 text-sm font-medium text-gray-700">中文成绩单</p>
            {cvStatus?.transcript?.cn?.uploaded ? (
              <p className="text-xs text-green-600 mt-1">✓ {cvStatus.transcript.cn.name} ({formatSize(cvStatus.transcript.cn.size)})</p>
            ) : (
              <p className="text-xs text-gray-400 mt-1">未上传</p>
            )}
            <input ref={tCnFileRef} type="file" accept=".pdf" className="hidden" onChange={(e) => handleTranscriptUpload('cn', e.target.files?.[0])} />
            <button
              onClick={() => tCnFileRef.current?.click()}
              disabled={uploading === 'transcript-cn'}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
            >
              {uploading === 'transcript-cn' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {cvStatus?.transcript?.cn?.uploaded ? '重新上传' : '上传 PDF'}
            </button>
          </div>
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-5 text-center hover:border-indigo-300 transition-colors">
            <FileText className="mx-auto h-8 w-8 text-gray-400" />
            <p className="mt-2 text-sm font-medium text-gray-700">英文成绩单 (Transcript)</p>
            {cvStatus?.transcript?.en?.uploaded ? (
              <p className="text-xs text-green-600 mt-1">✓ {cvStatus.transcript.en.name} ({formatSize(cvStatus.transcript.en.size)})</p>
            ) : (
              <p className="text-xs text-gray-400 mt-1">未上传</p>
            )}
            <input ref={tEnFileRef} type="file" accept=".pdf" className="hidden" onChange={(e) => handleTranscriptUpload('en', e.target.files?.[0])} />
            <button
              onClick={() => tEnFileRef.current?.click()}
              disabled={uploading === 'transcript-en'}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
            >
              {uploading === 'transcript-en' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {cvStatus?.transcript?.en?.uploaded ? '重新上传' : '上传 PDF'}
            </button>
          </div>
        </div>

        {/* 论文 */}
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm font-medium text-gray-700">论文（全部附上发送）</p>
          <input ref={paperFileRef} type="file" accept=".pdf" className="hidden" onChange={(e) => handlePaperUpload(e.target.files?.[0])} />
          <button
            onClick={() => paperFileRef.current?.click()}
            disabled={uploading?.startsWith('paper:') || false}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
          >
            {uploading?.startsWith('paper:') ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            添加论文
          </button>
        </div>
        {cvStatus?.papers && cvStatus.papers.length > 0 ? (
          <div className="space-y-2">
            {cvStatus.papers.map((p: any) => (
              <div key={p.name} className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="h-4 w-4 text-gray-400 shrink-0" />
                  <span className="text-sm text-gray-700 truncate">{p.name}</span>
                  <span className="text-xs text-gray-400 shrink-0">({formatSize(p.size)})</span>
                </div>
                <button
                  onClick={() => handlePaperDelete(p.name)}
                  disabled={uploading === `paper-del:${p.name}`}
                  className="text-gray-400 hover:text-red-500 disabled:opacity-50"
                  title="删除"
                >
                  {uploading === `paper-del:${p.name}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-400">暂无论文。点击「添加论文」上传 PDF。同名会覆盖。</p>
        )}
      </div>

      {/* 黑名单 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center gap-2 mb-2">
          <Ban className="h-5 w-5 text-red-500" />
          <h3 className="text-lg font-semibold text-gray-800">导师黑名单</h3>
          <span className="text-xs text-gray-400">（{blacklist.length}）</span>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          从列表里叉掉的导师会自动加入这里，<b>之后的自动搜索 Agent 不会再推荐他们</b>。从下方移除后可恢复。
        </p>
        {blacklist.length === 0 ? (
          <p className="text-xs text-gray-400">暂无。在导师列表点击 🗑 即可加入。</p>
        ) : (
          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {blacklist.map((b) => (
              <div key={b.id} className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-800 truncate">
                    {b.name} <span className="text-gray-400">·</span> <span className="text-gray-500">{b.university}</span>
                  </p>
                  {b.reason && <p className="text-xs text-gray-400 truncate">{b.reason}</p>}
                </div>
                <button
                  onClick={() => handleRemoveBlacklist(b.id)}
                  disabled={removingBlId === b.id}
                  className="ml-3 text-xs text-gray-500 hover:text-indigo-600 disabled:opacity-50 shrink-0"
                  title="移出黑名单（之后会重新被搜索推荐）"
                >
                  {removingBlId === b.id ? <Loader2 className="h-4 w-4 animate-spin" /> : '移出'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Profile 编辑 */}
      <div className="rounded-xl bg-white p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">写信参考资料（AI 看的，非简历）</h3>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setGenError(null); setGenModalOpen(true) }}
              className="inline-flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100"
              title="从已上传的 CV 自动生成 Profile 草稿"
            >
              <Sparkles className="h-4 w-4" />
              AI 生成
            </button>
            <button
              onClick={handleSaveProfile}
              disabled={savingProfile}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {savingProfile ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : savedProfile ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {savingProfile ? '保存中...' : savedProfile ? '已保存' : '保存'}
            </button>
          </div>
        </div>
        <p className="mb-3 text-sm text-gray-500">
          这份是 AI 写邮件时的参考资料（研究方向、PhD 计划、项目叙述化讲法、匹配偏好）。CV 已作为附件发给导师，<b>这里不要重复 CV 内容</b>。可点「AI 生成」从 CV 一键生成草稿后再编辑。
        </p>
        <textarea
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          rows={20}
          className="w-full rounded-lg border border-gray-300 px-4 py-3 font-mono text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          placeholder="点击右上角「AI 生成」从 CV 自动起草，或手动填写..."
        />
      </div>

      {/* AI 生成 Profile 弹窗 */}
      {genModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => !generating && setGenModalOpen(false)}>
          <div className="w-full max-w-xl rounded-2xl bg-white shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <div className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-indigo-500" />
                <h3 className="text-lg font-semibold text-gray-800">从 CV 生成 Profile</h3>
              </div>
              <button onClick={() => !generating && setGenModalOpen(false)} disabled={generating} className="text-gray-400 hover:text-gray-600 disabled:opacity-50">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-gray-600">
                AI 会读取已上传的 CV（优先 <code className="rounded bg-gray-100 px-1">个人简历.pdf</code>），结合你下方的补充说明，生成一份新的 Profile 草稿放进 textarea。<b>不会自动保存</b>——你可以再编辑后再点「保存」。
              </p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">补充说明（可选，但强烈建议填）</label>
                <p className="text-xs text-gray-400 mb-2">告诉 AI 那些 CV 里没有、但你希望它知道的事。比如：PhD 想偏哪个方向、目标地区、不想做的方向、需要强调或淡化的经历等。</p>
                <textarea
                  value={genPitch}
                  onChange={(e) => setGenPitch(e.target.value)}
                  rows={6}
                  disabled={generating}
                  placeholder="例：PhD 阶段想聚焦在 LLM-for-Optimization 这一条线，不太想做纯组合优化的求解器侧；目标地区中国 / 香港 / 新加坡；不要联系做纯 CV / 系统的导师；可以提一下我的 ICPC 背景作为算法功底信号。"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50"
                />
              </div>
              {genError && (
                <div className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {genError}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 px-6 py-4 bg-gray-50 border-t">
              <button onClick={() => setGenModalOpen(false)} disabled={generating} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50">取消</button>
              <button
                onClick={handleGenerateProfile}
                disabled={generating}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {generating ? '生成中...' : '生成'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
