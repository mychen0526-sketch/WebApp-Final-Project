// Thin client for the FastAPI backend. Errors come back as {code, message, detail}.
import { AuthError, authHeaders, signOut } from './auth.js'

export const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, { status, code, detail } = {}) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

const FIELD_LABEL = {
  goal: '主題',
  title: '標題',
  subtitle: '副標',
  tone: '語氣',
  audience: '受眾',
  instruction: '說明',
  caption_threads: 'Threads 文案',
  caption_instagram: 'Instagram 文案',
  caption_linkedin: 'LinkedIn 文案',
  canvas_json: '圖卡資料',
  platforms: '發布平台',
  query: '搜尋關鍵字',
  file: '檔案',
  name: '名稱',
  brand_name: '品牌名稱',
  default_tone: '預設語氣',
  default_audience: '主要受眾',
  default_platforms: '預設平台',
  sensitive_words: '敏感詞',
  when: '排程時間',
}

function fieldLabel(loc = []) {
  const key = [...loc].reverse().find((part) => typeof part === 'string' && FIELD_LABEL[part]) || loc[loc.length - 1]
  return FIELD_LABEL[key] || (typeof key === 'string' ? key : '欄位')
}

// BUG-19: turn FastAPI / Pydantic English validation text into short Chinese.
function translateValidation(msg = '') {
  const text = String(msg)
  const atMost = text.match(/at most (\d+) characters/i)
  if (atMost) return `最多 ${atMost[1]} 字`
  const atLeast = text.match(/at least (\d+) characters/i)
  if (atLeast) return `至少 ${atLeast[1]} 字`
  if (/field required/i.test(text)) return '必填'
  if (/input should be/i.test(text)) return '格式不正確'
  if (/value is not a valid/i.test(text)) return '格式不正確'
  if (/string should match/i.test(text)) return '格式不正確'
  return text
}

function messageOf(data, status) {
  if (data?.message) return data.message
  // FastAPI request validation errors: {detail: [{loc, msg}]}
  if (Array.isArray(data?.detail)) {
    return data.detail.map((item) => `${fieldLabel(item.loc)}：${translateValidation(item.msg)}`).join('；')
  }
  if (typeof data?.detail === 'string') return translateValidation(data.detail)
  if (typeof data?.detail?.message === 'string') return data.detail.message
  return `後端回應錯誤（${status}）`
}

export const isAbort = (error) => error?.name === 'AbortError'

export async function request(path, { method = 'GET', body, form, auth = true, signal } = {}) {
  const headers = auth ? await authHeaders() : {}
  let payload
  if (form) {
    payload = form
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let response
  try {
    const init = { method, headers, signal }
    if (payload !== undefined) init.body = payload
    response = await fetch(`${API_BASE}${path}`, init)
  } catch (error) {
    if (isAbort(error)) throw error
    throw new ApiError(`連不到後端 ${API_BASE}，請確認 uvicorn 有在跑`, { status: 0, code: 'network' })
  }
  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (response.status === 401) {
    signOut()
    throw new AuthError(messageOf(data, 401))
  }
  if (!response.ok) {
    throw new ApiError(messageOf(data, response.status), { status: response.status, code: data?.code, detail: data?.detail })
  }
  return data
}

const json = (method) => (path, body, options) => request(path, { method, body: body ?? {}, ...options })

/**
 * Follow a generating post over server-sent events.
 * Calls onProgress({stage, threads}) as the copy is written; resolves with the post once it has
 * left `generating`. Throws if the stream cannot be opened (the caller then falls back to polling).
 */
async function followPost(id, { onProgress, signal } = {}) {
  const headers = await authHeaders()
  const response = await fetch(`${API_BASE}/api/posts/${id}/stream`, { headers, signal })
  if (response.status === 401) {
    signOut()
    throw new AuthError('登入已過期，請重新登入')
  }
  if (!response.ok || !response.body) throw new ApiError(`串流無法開啟（${response.status}）`, { status: response.status, code: 'stream' })
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value.replaceAll('\r\n', '\n')
    let cut
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      const payload = JSON.parse(data)
      if (event === 'progress') onProgress?.(payload)
      if (event === 'done') {
        reader.cancel().catch(() => {})
        if (!payload.post) throw new ApiError('找不到這篇貼文', { status: 404 })
        return payload.post
      }
      if (event === 'timeout') throw new ApiError('等太久了，請到內容資料庫重新整理看看', { code: 'stream' })
    }
  }
  throw new ApiError('串流提早結束', { code: 'stream' })
}

export const api = {
  health: () => request('/health', { auth: false }),
  candidates: (goal, tone, signal) => json('POST')('/api/candidates', { goal, tone }, { signal }),
  research: (query, signal) => json('POST')('/api/research', { query }, { signal }),
  listPosts: () => request('/api/posts'),
  getPost: (id) => request(`/api/posts/${id}`),
  createPost: (body) => json('POST')('/api/posts', body),
  regenerate: (id, body) => json('POST')(`/api/posts/${id}/generate`, body),
  followPost,
  cancel: (id) => json('POST')(`/api/posts/${id}/cancel`),
  adjust: (id, body, signal) => json('POST')(`/api/posts/${id}/adjust`, body, { signal }),
  savePost: (id, body) => json('PATCH')(`/api/posts/${id}`, body),
  deletePost: (id) => request(`/api/posts/${id}`, { method: 'DELETE' }),
  uploadImage(id, blob, source = 'exported') {
    const form = new FormData()
    form.append('file', blob, `${source}.png`)
    form.append('source', source)
    return request(`/api/posts/${id}/images`, { method: 'POST', form })
  },
  feedback: (id, rating) => json('POST')(`/api/posts/${id}/feedback`, { rating }),
  listFeedback: () => request('/api/feedback'),
  submit: (id, platforms) => json('POST')(`/api/posts/${id}/submit`, { platforms }),
  reject: (id) => json('POST')(`/api/posts/${id}/reject`),
  approve: (id) => json('POST')(`/api/posts/${id}/approve`, { readConfirmed: true, rightsConfirmed: true }),
  publish: (id) => json('POST')(`/api/posts/${id}/publish`),
  retry: (id, body) => json('POST')(`/api/posts/${id}/retry`, body || {}),
  schedule: (id, when) => json('POST')(`/api/posts/${id}/schedule`, { when }),
  cancelSchedule: (id) => json('POST')(`/api/posts/${id}/cancel-schedule`),
  reopen: (id) => json('POST')(`/api/posts/${id}/reopen`),
  getSettings: () => request('/api/settings'),
  putSettings: (body) => json('PUT')('/api/settings', body),
  accounts: () => request('/api/accounts'),
  connect: (platform) => request(`/api/accounts/${platform}/connect`),
  disconnect: (platform) => request(`/api/accounts/${platform}`, { method: 'DELETE' }),
  listTemplates: () => request('/api/templates'),
  uploadTemplate(file, name) {
    const form = new FormData()
    form.append('file', file)
    form.append('name', name)
    return request('/api/templates', { method: 'POST', form })
  },
  deleteTemplate: (id) => request(`/api/templates/${id}`, { method: 'DELETE' }),
}
