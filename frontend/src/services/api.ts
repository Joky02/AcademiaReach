import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// ── Stats ────────────────────────────────────────────
export const getStats = () => api.get('/stats')

// ── Professors ───────────────────────────────────────
export const getProfessors = () => api.get('/professors')
export const addProfessor = (data: any) => api.post('/professors', data)
export const deleteProfessor = (id: number) => api.delete(`/professors/${id}`)
export const updateProfessor = (id: number, data: any) => api.put(`/professors/${id}`, data)
export const toggleStar = (id: number) => api.put(`/professors/${id}/star`)
export const updateProfTags = (id: number, tags: string[]) =>
  api.put(`/professors/${id}/tags`, { tags })
export const enrichProfessor = (id: number) => api.post(`/professors/${id}/enrich`)
export const startSearch = (data: any) => api.post('/search/start', data)
export const stopSearch = () => api.post('/search/stop')

// ── Drafts ───────────────────────────────────────────
export const getDrafts = (status?: string) =>
  api.get('/drafts', { params: status ? { status } : {} })
export const getDraft = (id: number) => api.get(`/drafts/${id}`)
export const updateDraft = (id: number, data: any) => api.put(`/drafts/${id}`, data)
export const deleteDraft = (id: number) => api.delete(`/drafts/${id}`)
export const startCompose = (professorIds?: number[]) =>
  api.post('/compose/start', { professor_ids: professorIds || null })

// ── Send ─────────────────────────────────────────────
export const sendEmail = (draftId: number) => api.post(`/send/${draftId}`)
export const sendBatch = (draftIds: number[]) =>
  api.post('/send/batch', { draft_ids: draftIds })

// ── Replies ──────────────────────────────────────────
export const getReplies = () => api.get('/replies')
export const checkReplies = () => api.post('/replies/check')
export const markReplyRead = (id: number) => api.put(`/replies/${id}/read`)

// ── Config ───────────────────────────────────────────
export const getProfile = () => api.get('/config/profile')
export const updateProfile = (content: string) =>
  api.put('/config/profile', { content })
export const getSettings = () => api.get('/config/settings')

// ── CV 简历管理 ──────────────────────────────────────
export const getCvStatus = () => api.get('/config/cv')
export const uploadCv = (lang: 'cn' | 'en', file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/config/cv/${lang}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ── 搜索关键词 ──────────────────────────────────────
export const updateKeywords = (keywords: string[], regions?: string[]) =>
  api.put('/config/keywords', { keywords, regions })

// ── 邮箱验证 ────────────────────────────────────────
export const getEmailConfig = () => api.get('/config/email')
export const verifyEmail = (data: any) => api.post('/config/email/verify', data)

// ── 自定义 Prompt ───────────────────────────────────
export const getPrompts = () => api.get('/config/prompts')
export const updatePrompts = (data: any) => api.put('/config/prompts', data)

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
