import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// ── Stats ────────────────────────────────────────────
export const getStats = () => api.get('/stats')

// ── Professors ───────────────────────────────────────
export const getProfessors = () => api.get('/professors')
export const getProfessor = (id: number) => api.get(`/professors/${id}`)
export const addProfessor = (data: any) => api.post('/professors', data)
export const deleteProfessor = (id: number, blacklist = true) =>
  api.delete(`/professors/${id}`, { params: { blacklist } })

// ── 黑名单 ──────────────────────────────────────────
export const getBlacklist = () => api.get('/blacklist')
export const removeFromBlacklist = (id: number) => api.delete(`/blacklist/${id}`)
export const updateProfessor = (id: number, data: any) => api.put(`/professors/${id}`, data)
export const toggleStar = (id: number) => api.put(`/professors/${id}/star`)
export const updateProfTags = (id: number, tags: string[]) =>
  api.put(`/professors/${id}/tags`, { tags })
export const enrichProfessor = (id: number) => api.post(`/professors/${id}/enrich`)
export const startEnrichProfessor = (id: number) => api.post(`/professors/${id}/enrich/start`)
export const getEnrichStatus = () => api.get('/professors/enrich/status')
export const startSearch = (data: any) => api.post('/search/start', data)
export const stopSearch = () => api.post('/search/stop')
export const getSearchStatus = () => api.get('/search/status')

// ── Drafts ───────────────────────────────────────────
export const getDrafts = (status?: string) =>
  api.get('/drafts', { params: status ? { status } : {} })
export const getDraftSummaries = () => api.get('/drafts/summary')
export const getDraftReview = (status?: string) =>
  api.get('/drafts/review', { params: { status: status || '' } })
export const getDraft = (id: number) => api.get(`/drafts/${id}`)
export const updateDraft = (id: number, data: any) => api.put(`/drafts/${id}`, data)
export const deleteDraft = (id: number) => api.delete(`/drafts/${id}`)
export const startCompose = (
  professorIds?: number[],
  replaceExisting = false,
  runDeepResearch = true,
  parallelism = 1,
) =>
  api.post('/compose/start', {
    professor_ids: professorIds || null,
    replace_existing: replaceExisting,
    run_deep_research: runDeepResearch,
    parallelism,
  })
export const getComposeStatus = () => api.get('/compose/status')
export const startPaperRecommendations = (professorIds: number[]) =>
  api.post('/paper-recommendations/start', { professor_ids: professorIds })
export const getPaperRecommendationStatus = () => api.get('/paper-recommendations/status')

// ── Send ─────────────────────────────────────────────
export const sendEmail = (draftId: number, includeCc = false) =>
  api.post(`/send/${draftId}`, { include_cc: includeCc })
export const sendBatch = (draftIds: number[], includeCc = false) =>
  api.post('/send/batch', { draft_ids: draftIds, include_cc: includeCc })

// ── Replies ──────────────────────────────────────────
export const getReplies = () => api.get('/replies')
export const checkReplies = () => api.post('/replies/check')
export const markReplyRead = (id: number) => api.put(`/replies/${id}/read`)

// ── Config ───────────────────────────────────────────
export const getProfile = () => api.get('/config/profile')
export const updateProfile = (content: string) =>
  api.put('/config/profile', { content })
export const generateProfile = (pitch?: string) =>
  api.post('/config/profile/generate', { pitch })
export const getSettings = () => api.get('/config/settings')
export const updateLlmConfig = (data: any) => api.put('/config/llm', data)

// ── CV / 成绩单 / 论文 附件管理 ──────────────────────
export const getCvStatus = () => api.get('/config/cv')
export const uploadCv = (lang: 'cn' | 'en', file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/config/cv/${lang}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const uploadTranscript = (lang: 'cn' | 'en', file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/config/transcript/${lang}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const uploadPaper = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/config/papers', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deletePaper = (name: string) =>
  api.delete(`/config/papers/${encodeURIComponent(name)}`)

// ── 搜索关键词 ──────────────────────────────────────
export const updateKeywords = (keywords: string[], regions?: string[]) =>
  api.put('/config/keywords', { keywords, regions })

// ── 邮箱验证 ────────────────────────────────────────
export const getEmailConfig = () => api.get('/config/email')
export const verifyEmail = (data: any) => api.post('/config/email/verify', data)

// ── 自定义 Prompt ───────────────────────────────────
export const getPrompts = () => api.get('/config/prompts')
export const updatePrompts = (data: any) => api.put('/config/prompts', data)

// ── Prompt 模板（backend/prompts/*.md）────────────────
export const getPromptTemplates = () => api.get('/config/prompt-templates')
export const updatePromptTemplate = (name: string, content: string) =>
  api.put(`/config/prompt-templates/${name}`, { content })

// ── WebSocket ────────────────────────────────────────
export function connectWebSocket(onMessage: (data: any) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/progress`)

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onMessage(data)
    } catch (e) {
      console.error('WebSocket parse error:', e)
    }
  }

  ws.onclose = () => {
    // 自动重连
    setTimeout(() => connectWebSocket(onMessage), 3000)
  }

  // 心跳
  const heartbeat = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send('ping')
    } else {
      clearInterval(heartbeat)
    }
  }, 30000)

  return ws
}

export default api
