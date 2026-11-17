// Mapping between backend posts (snake_case, English statuses) and the studio's draft items.

export const STATUS_LABEL = {
  generating: '生成中',
  generation_failed: '生成失敗',
  editing: '草稿',
  pending_review: '待審核',
  approved: '已核准',
  scheduled: '已排程',
  publishing: '發布中',
  published: '已發布',
  partially_published: '部分發布',
  publish_failed: '發布失敗',
}

// Platforms the backend can really publish to. X and Telegram stay demo-only in the UI.
export const REAL_PLATFORMS = { Threads: 'threads', Instagram: 'instagram' }
export const PLATFORM_NAME = { threads: 'Threads', instagram: 'Instagram' }
export const isRealPlatform = (name) => Boolean(REAL_PLATFORMS[name])

const pad = (n) => String(n).padStart(2, '0')

export function shortDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`
}

export function localStamp(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// Value for <input type="datetime-local">, one hour from now on the hour.
export function defaultScheduleInput() {
  const d = new Date(Date.now() + 60 * 60 * 1000)
  d.setMinutes(0, 0, 0)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`
}

// "2026-11-20T09:00" (local) → "2026-11-20T09:00:00+08:00" (the backend needs a time zone)
export function withLocalOffset(value) {
  const d = new Date(value)
  const offset = -d.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const abs = Math.abs(offset)
  return `${value.length === 16 ? `${value}:00` : value}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
}

// Where the text block sits on the card for each backend layout (percent of the card).
const TEXT_SPOT = {
  top: { x: 50, y: 26 },
  bottom: { x: 50, y: 76 },
  center: { x: 50, y: 24 },
  left: { x: 36, y: 46 },
}

export function layoutFromCanvas(canvas) {
  if (canvas?.ui?.layout) return canvas.ui.layout
  const text = TEXT_SPOT[canvas?.layout] || TEXT_SPOT.top
  return { image: { x: 50, y: text.y > 50 ? 30 : 70 }, text }
}

// Backend layout name to ask for, from where the user put the text on the card.
export function layoutName(layout) {
  return layout?.text?.y > 50 ? 'bottom' : 'top'
}

function textOf(canvas, type) {
  return (canvas?.texts || []).find((item) => item.textType === type)?.text || ''
}

export function toDraft(post) {
  const canvas = post.canvas_json || {}
  const images = post.images || []
  const generated = images.filter((item) => item.source === 'generated' || item.source === 'template')
  return {
    id: post.id,
    post,
    rawStatus: post.status,
    status: STATUS_LABEL[post.status] || post.status,
    title: (canvas.ui?.title && canvas.ui.title.replaceAll('\n', ' ') === post.title ? canvas.ui.title : post.title)
      || post.selected_prompt?.title || '（尚未命名）',
    subtitle: canvas.ui?.subtitle ?? textOf(canvas, 'highlight'),
    content: post.caption_threads || '',
    igCaption: post.caption_instagram || '',
    goal: post.goal,
    tone: post.tone,
    audience: post.audience,
    date: shortDate(post.updated_at || post.created_at),
    when: post.scheduled_at ? localStamp(post.scheduled_at) : null,
    scheduledAt: post.scheduled_at || null,
    destinations: (post.platforms || []).map((p) => PLATFORM_NAME[p] || p),
    layout: layoutFromCanvas(canvas),
    style: Number.isInteger(canvas.style) ? canvas.style : 0,
    font: canvas.ui?.font ?? 30,
    templateId: canvas.template_id || null,
    background: canvas.ui?.background === false ? null : canvas.image?.url || generated.at(-1)?.public_url || null,
    error: post.generation_error || null,
    publications: post.publications || [],
  }
}

// Merge a list response (no images/publications) into an existing draft without losing them.
export function mergeDraft(old, post) {
  const next = toDraft({ ...old?.post, ...post })
  if (!post.images && old) next.publications = old.publications
  return next
}

// What the editor sends back on save.
export function patchBody(state) {
  const canvas = state.canvas || {}
  const texts = (canvas.texts || []).map((item) => {
    if (item.textType === 'headline') return { ...item, text: state.title.replaceAll('\n', ' ').slice(0, 60) || item.text }
    if (item.textType === 'highlight' && state.subtitle) return { ...item, text: state.subtitle.slice(0, 60) }
    return item
  })
  return {
    title: state.title.replaceAll('\n', ' ').slice(0, 200),
    caption_threads: state.content,
    caption_instagram: state.igCaption,
    tone: state.tone,
    audience: state.audience,
    canvas_json: {
      ...canvas,
      style: state.style,
      texts,
      ui: { layout: state.layout, font: state.font, subtitle: state.subtitle, title: state.title },
    },
  }
}

export const isBusy = (rawStatus) => rawStatus === 'generating' || rawStatus === 'publishing'
