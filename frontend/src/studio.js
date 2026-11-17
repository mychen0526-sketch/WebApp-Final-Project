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
export const PLATFORMS = ['Threads', 'X', 'Instagram', 'Telegram']
export const PLATFORM_HINT = {
  Threads: '話題討論 · 由後端正式發布',
  X: '短文貼文 · 示範平台，尚未串接',
  Instagram: '正方形圖文 · 由後端正式發布',
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
    // editor fields for the post that is open (activeId = backend post id)
    content: '',
    igCaption: '',
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
    platform: 'Threads',
    platforms: ['Threads'],
    drafts: [],
    sources: [
      { title: '生成式 AI 加速企業產品開發流程', type: '產業觀察', origin: '示範資料 · Tech Insights', date: '2026/10/16', summary: '整理企業如何使用生成式 AI 進行開發、設計與業務流程。' },
      { title: 'AI Agent 在新創公司的應用機會', type: '科技新聞', origin: '示範資料 · AI Daily', date: '2026/10/15', summary: '探討 Agent 技術如何協助中小型團隊擴大交付能力。' },
      { title: 'Human-AI Collaboration in Product Design', type: '學術研究', origin: '示範資料 · Research Digest', date: '2026/10/14', summary: '人機協作在產品設計工作流程中的效率及品質討論。' },
      { title: '2026 科技新創產業趨勢觀察', type: '市場趨勢', origin: '示範資料 · Market Lab', date: '2026/10/12', summary: '市場轉向速度、AI 商業化與小型創業團隊策略。' },
    ],
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

// Threads and Instagram show the captions the backend wrote; X and Telegram are demo previews.
export function platformCaption(state, platform) {
  if (platform === 'Instagram') return state.igCaption || state.content
  let text = state.content
  if (platform === 'X' && text.length > 240) text = `${text.slice(0, 237)}…`
  return text
}

export function scanText(sensitive, title, content) {
  const detected = sensitive.filter((word) => content.includes(word) || title.includes(word))
  let risks = detected.length ? `偵測到可能敏感詞：${detected.join('、')}` : '未偵測到自訂機密關鍵字'
  if (/保證賺錢|絕對安全|百分之百/.test(content)) risks += '；另有待確認的絕對性宣稱'
  return { detected, risks }
}

export function safetyScan(state) {
  return scanText(state.sensitive, `${state.title}\n${state.subtitle || ''}`, `${state.content}\n${state.igCaption || ''}`)
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

// What sits behind the text on the card: a chosen template, else the AI picture, else the gradient.
export function cardBackground(state) {
  return templateUrl(state) || state.background || null
}

export function pageTitle(page) {
  return MENU.find(([id]) => id === page)?.[1] || ''
}

export function reviewCount(state) {
  return state.drafts.filter((item) => item.status === '待審核').length
}
