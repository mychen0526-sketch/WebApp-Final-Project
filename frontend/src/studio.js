export const MENU = [
  ['workspace', 'AI 創作工作台'],
  ['discover', '趨勢情報中心'],
  ['library', '內容資料庫'],
  ['calendar', '發文排程日曆'],
  ['review', '內容審核'],
  ['templates', '品牌版型中心'],
  ['settings', '偏好與安全設定'],
]

export const TONES = ['專業分析', '輕鬆分享', '討論互動']
export const AUDIENCES = ['創業者與科技從業者', '一般大眾', '潛在企業客戶', '學術研究者']
export const PLATFORMS = ['Threads', 'X', 'Instagram', 'Telegram']
export const PLATFORM_HINT = {
  Threads: '話題討論',
  X: '短文貼文',
  Instagram: '正方形圖文',
  Telegram: '頻道圖文',
}

export const STYLES = [
  ['#31406a', '#8d84d6', '科技深藍'],
  ['#35524f', '#7eb8b0', '薄荷科技'],
  ['#7a4d6c', '#e3b7c6', '未來粉紫'],
  ['#4a4032', '#d4bc90', '精品暖金'],
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

export const DEFAULT_CONTENT =
  'AI 正在改變產品商業化的速度。從原型驗證、後端整合到正式上線，今天的創業團隊能更快將想法交付市場。\n\n但真正的競爭力，不只是寫得更快，而是能否持續理解使用者，並將技術轉化成價值。\n\n#人工智慧 #科技趨勢 #產品開發'

export function initialState() {
  return {
    page: 'workspace',
    stage: 'write',
    prompt: '整理近期 AI 產品商業化趨勢，撰寫一篇給創業者看的科技觀察貼文。',
    tone: '專業分析',
    audience: '創業者與科技從業者',
    content: DEFAULT_CONTENT,
    title: 'AI 如何加速\n產品商業化？',
    style: 0,
    font: 30,
    layout: { image: { x: 50, y: 30 }, text: { x: 50, y: 72 } },
    series: [],
    activeId: null,
    platform: 'Threads',
    platforms: [...PLATFORMS],
    drafts: [
      { id: 1, title: 'AI 如何加速產品商業化？', content: DEFAULT_CONTENT, status: '草稿', date: '10/17', layout: { image: { x: 50, y: 30 }, text: { x: 50, y: 72 } }, style: 0, font: 30 },
      { id: 2, title: '從原型到上市：團隊如何縮短迭代週期', content: '產品開發需要有效率的跨職能協作。', status: '待審核', date: '10/16', layout: { image: { x: 50, y: 30 }, text: { x: 50, y: 72 } }, style: 1, font: 30 },
      { id: 3, title: '生成式 AI 的最新應用方向', content: '今天來聊聊生成式 AI。', status: '已發布', date: '10/14', when: '2026-10-14 現在', destinations: ['Threads'] },
      { id: 4, title: '小型團隊的 AI 工作流', content: '先挑一個重複的流程，再決定要不要自動化。', status: '已核准', date: '10/18', layout: { image: { x: 50, y: 30 }, text: { x: 50, y: 72 } }, style: 2, font: 30 },
      { id: 5, title: '下週的產品觀察', content: '這則已排程，取消後會回到已核准。', status: '已排程', date: '10/19', when: '2026-10-21 10:00', destinations: ['Threads', 'Instagram'], layout: { image: { x: 50, y: 74 }, text: { x: 50, y: 28 } }, style: 0, font: 30 },
    ],
    sources: [
      { title: '生成式 AI 加速企業產品開發流程', type: '產業觀察', origin: '示範資料 · Tech Insights', date: '2026/10/16', summary: '整理企業如何使用生成式 AI 進行開發、設計與業務流程。' },
      { title: 'AI Agent 在新創公司的應用機會', type: '科技新聞', origin: '示範資料 · AI Daily', date: '2026/10/15', summary: '探討 Agent 技術如何協助中小型團隊擴大交付能力。' },
      { title: 'Human-AI Collaboration in Product Design', type: '學術研究', origin: '示範資料 · Research Digest', date: '2026/10/14', summary: '人機協作在產品設計工作流程中的效率及品質討論。' },
      { title: '2026 科技新創產業趨勢觀察', type: '市場趨勢', origin: '示範資料 · Market Lab', date: '2026/10/12', summary: '市場轉向速度、AI 商業化與小型創業團隊策略。' },
    ],
    sensitive: ['未公開產品', '內部代號', '機密客戶'],
    feedback: [],
    company: 'ORBIT / LAB',
    themeName: '科技深藍',
  }
}

export function platformCaption(content, platform) {
  let text = content
  if (platform === 'X' && text.length > 240) text = `${text.slice(0, 237)}…`
  if (platform === 'Instagram') text = `科技趨勢分享\n\n${text}`
  return text
}

export function scanText(sensitive, title, content) {
  const detected = sensitive.filter((word) => content.includes(word) || title.includes(word))
  let risks = detected.length ? `偵測到可能敏感詞：${detected.join('、')}` : '未偵測到自訂機密關鍵字'
  if (/保證賺錢|絕對安全|百分之百/.test(content)) risks += '；另有待確認的絕對性宣稱'
  return { detected, risks }
}

export function safetyScan(state) {
  return scanText(state.sensitive, state.title, state.content)
}

export function activeDraft(state) {
  return state.drafts.find((item) => item.id === state.activeId) || null
}

export function stageEnabled(state, stage) {
  const status = activeDraft(state)?.status
  if (stage === 'write' || stage === 'edit') return !status || status === '草稿'
  if (stage === 'review') return status === '待審核'
  if (stage === 'publish') return status === '已核准' || status === '已排程' || status === '已發布'
  return false
}

export function pageTitle(page) {
  return MENU.find(([id]) => id === page)?.[1] || ''
}

export function reviewCount(state) {
  return state.drafts.filter((item) => item.status === '待審核').length
}
