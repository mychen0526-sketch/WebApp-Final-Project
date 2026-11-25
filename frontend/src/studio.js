export const MENU = [
  ['workspace', '寫貼文'],
  ['library', '我的貼文'],
  ['review', '待你確認'],
  ['calendar', '排程'],
  ['discover', '趨勢情報'],
  ['templates', '品牌版型'],
  ['settings', '偏好設定'],
]

/** Daily path: keep these at the top of the sidebar. */
export const MENU_PRIMARY = ['workspace', 'library', 'review', 'calendar']
/** Secondary tools: collapsed under「更多」 so the main path stays clear. */
export const MENU_MORE = ['discover', 'templates', 'settings']

export const TONES = ['專業分析', '輕鬆分享', '討論互動']
export const AUDIENCES = ['創業者與科技從業者', '一般大眾', '潛在企業客戶', '學術研究者']
/** Language of the generated copy and card text (backend `language`). */
export const LANGUAGES = [
  ['zh', '中文', '繁體中文文案'],
  ['en', 'English', '英文文案與圖卡'],
  ['both', '中英雙語', '中文在前、英文在後；圖卡主標中文、說明英文'],
]
export const PLATFORMS = ['Threads', 'Instagram', 'LinkedIn', 'X', 'Telegram']
export const PLATFORM_HINT = {
  Threads: '話題討論 · 由後端正式發布',
  X: '短文貼文 · 示範平台，尚未串接',
  Instagram: '正方形圖文 · 由後端正式發布',
  LinkedIn: '專業觀點長文 · 由後端正式發布到個人動態',
  Telegram: '頻道圖文 · 示範平台，尚未串接',
}

export const STYLES = [
  ['#1f2a37', '#5d6b7c', '墨藍'],
  ['#2c4a3e', '#7fa08f', '松綠'],
  ['#4a3428', '#b08968', '焦糖'],
  ['#3a2f2a', '#c4a484', '暖砂'],
]

export const DEFAULT_LAYOUT = {
  image: { x: 50, y: 30 },
  text: { x: 50, y: 72 },
}

export function layoutPreset(place) {
  if (place === 'bottom') return { image: { x: 50, y: 74 }, text: { x: 50, y: 28 } }
  return { image: { x: 50, y: 30 }, text: { x: 50, y: 72 } }
}

export const STAGES = [
  ['write', '撰寫'],
  ['edit', '編輯'],
  ['review', '審核'],
  ['publish', '發布'],
]

export function initialState() {
  return {
    page: 'workspace',
    stage: 'write',
    prompt: '整理近期 AI 產品商業化趨勢，撰寫一篇給創業者看的科技觀察貼文。',
    tone: '專業分析',
    audience: '創業者與科技從業者',
    language: 'zh',
    // editor fields for the post that is open (activeId = backend post id)
    content: '',
    igCaption: '',
    linkedinCaption: '',
    title: '',
    subtitle: '',
    canvas: null,
    background: null,
    style: 0,
    font: 30,
    layout: { image: { x: 50, y: 30 }, text: { x: 50, y: 72 } },
    series: [],
    activeId: null,
    candidates: [],
    busy: null,
    progress: null, // {stage, threads} while AI writes, from the generation stream
    versionId: null, // which AI version the editor was loaded from (posts.versions[].id)
    platform: 'Threads',
    platforms: ['Threads'],
    drafts: [],
    // 趨勢情報: news found by POST /api/research, and the article this post is based on
    research: { query: '', results: [], backend: null, loading: false, error: null },
    reference: null, // {title, url, source, published, summary, image_url}
    imageMode: 'photo', // how reference.image_url is used: photo | blend | ai (no picture)
    credit: null, // 「圖片來源：…」 drawn on the card when a news picture is the background
    imageNote: null, // why the news picture could not be used, from the last generation
    sensitive: ['未公開產品', '內部代號', '機密客戶'],
    feedback: [],
    company: 'ORBIT / LAB',
    themeName: '墨藍',
    templates: [],
    templateId: null,
    removedTemplates: {},
    accounts: [],
    health: null,
  }
}

// Threads, Instagram and LinkedIn show the captions the backend wrote; X and Telegram are demo previews.
export function platformCaption(state, platform) {
  if (platform === 'Instagram') return state.igCaption || state.content
  if (platform === 'LinkedIn') return state.linkedinCaption || state.igCaption || state.content
  let text = state.content
  if (platform === 'X' && text.length > 240) text = `${text.slice(0, 237)}…`
  return text
}

// Same normalization as backend/app/services/safety.py: full-width → half-width (NFKC),
// case-insensitive, whitespace and zero-width characters ignored. Keep the two in sync.
const IGNORED = /[\s​-‏⁠-⁤﻿­᠎]+/g
export const normalizeText = (text) => (text || '').normalize('NFKC').replace(IGNORED, '').toLowerCase()

export function scanText(sensitive, title, content) {
  const haystack = normalizeText(`${title}\n${content}`)
  const detected = sensitive.filter((word) => {
    const needle = normalizeText(word)
    return needle && haystack.includes(needle)
  })
  let risks = detected.length ? `偵測到可能敏感詞：${detected.join('、')}` : '未偵測到自訂機密關鍵字'
  if (/保證賺錢|絕對安全|百分之百/.test(normalizeText(content))) risks += '；另有待確認的絕對性宣稱'
  return { detected, risks }
}

export function safetyScan(state) {
  const captions = [state.content, state.igCaption, state.linkedinCaption].filter(Boolean).join('\n')
  return scanText(state.sensitive, `${state.title}\n${state.subtitle || ''}`, captions)
}

export function activeDraft(state) {
  return state.drafts.find((item) => item.id === state.activeId) || null
}

export function stageEnabled(state, stage) {
  const status = activeDraft(state)?.status
  if (stage === 'write') return !status || status === '草稿' || status === '生成失敗' || status === '生成中'
  if (stage === 'edit') return status === '草稿'
  if (stage === 'review') return status === '待審核'
  if (stage === 'publish') return ['已核准', '已排程', '發布中', '已發布', '部分發布', '發布失敗'].includes(status)
  return false
}

export function templateOf(state, id = state.templateId) {
  return state.templates.find((item) => item.id === id) || null
}

// 已移除的模板仍要能畫出用過它的內容
export function templateUrl(state, id = state.templateId) {
  if (!id) return null
  return templateOf(state, id)?.url || state.removedTemplates?.[id] || null
}

// What sits behind the text on the card: a chosen template, else the AI picture / news photo, else the gradient.
export function cardBackground(state) {
  return templateUrl(state) || state.background || null
}

// Credit line on the card: only when the picture behind the text is a news photo (not a template).
export function cardCredit(state) {
  return !state.templateId && state.background ? state.credit : null
}

export function pageTitle(page) {
  return MENU.find(([id]) => id === page)?.[1] || ''
}

export function reviewCount(state) {
  return state.drafts.filter((item) => item.status === '待審核').length
}
