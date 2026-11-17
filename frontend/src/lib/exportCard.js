// Draws the card exactly as the editor shows it (background + brand + title + subtitle) onto a
// 1080×1080 canvas and returns a PNG Blob. The backend publishes this "exported" image, because
// the AI background it generated has no text on it.

const SIZE = 1080
const FONT = "'DM Sans', 'Noto Sans TC', sans-serif"

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('背景圖載入失敗'))
    img.src = url
  })
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

// Wrap by explicit newlines, then by width (character by character, which suits CJK text).
function wrap(ctx, text, maxWidth) {
  const lines = []
  for (const paragraph of String(text).split('\n')) {
    let line = ''
    for (const char of paragraph) {
      if (ctx.measureText(line + char).width > maxWidth && line) {
        lines.push(line)
        line = char
      } else {
        line += char
      }
    }
    lines.push(line)
  }
  return lines
}

/**
 * @param {object} card { style: [colorA, colorB], background, company, title, subtitle, font, layout }
 * @param {number} boardWidth on-screen width of the artboard, so sizes scale like the preview
 */
export async function exportCard(card, boardWidth = 520) {
  const scale = SIZE / Math.max(320, boardWidth)
  const canvas = document.createElement('canvas')
  canvas.width = SIZE
  canvas.height = SIZE
  const ctx = canvas.getContext('2d')

  // background
  const gradient = ctx.createLinearGradient(SIZE * 0.33, 0, SIZE * 0.67, SIZE)
  gradient.addColorStop(0, card.style[0])
  gradient.addColorStop(1, card.style[1])
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, SIZE, SIZE)
  if (card.background) {
    const img = await loadImage(card.background)
    const ratio = Math.max(SIZE / img.width, SIZE / img.height)
    const w = img.width * ratio
    const h = img.height * ratio
    ctx.drawImage(img, (SIZE - w) / 2, (SIZE - h) / 2, w, h)
  }

  const blockWidth = Math.min(SIZE * 0.72, 380 * scale)

  // decorative shape (only when there is no picture behind)
  if (!card.background) {
    const h = 148 * scale
    const x = (card.layout.image.x / 100) * SIZE - blockWidth / 2
    const y = (card.layout.image.y / 100) * SIZE - h / 2
    roundRect(ctx, x, y, blockWidth, h, 18 * scale)
    ctx.fillStyle = 'rgba(255,255,255,0.12)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.38)'
    ctx.lineWidth = 1.5 * scale
    ctx.stroke()
  }

  // text block: brand, title, subtitle — centred on layout.text like the CSS translate(-50%, -50%)
  const kickerSize = 11 * scale
  const titleSize = card.font * scale
  const subSize = Math.max(14, card.font * 0.5) * scale
  ctx.font = `600 ${titleSize}px ${FONT}`
  const titleLines = wrap(ctx, card.title || '', blockWidth)
  ctx.font = `400 ${subSize}px ${FONT}`
  const subLines = card.subtitle ? wrap(ctx, card.subtitle, blockWidth) : []
  const titleLead = titleSize * 1.25
  const subLead = subSize * 1.4
  const height = kickerSize * 1.6 + 8 * scale + titleLines.length * titleLead + (subLines.length ? 10 * scale + subLines.length * subLead : 0)
  const left = (card.layout.text.x / 100) * SIZE - blockWidth / 2
  let y = (card.layout.text.y / 100) * SIZE - height / 2

  ctx.fillStyle = '#fff'
  ctx.textBaseline = 'top'
  if (card.background) {
    ctx.shadowColor = 'rgba(0,0,0,0.35)'
    ctx.shadowBlur = 6 * scale
    ctx.shadowOffsetY = 1 * scale
  }
  ctx.globalAlpha = 0.8
  ctx.font = `400 ${kickerSize}px ${FONT}`
  ctx.fillText(String(card.company || '').split('').join(String.fromCharCode(8202)), left, y)
  ctx.globalAlpha = 1
  y += kickerSize * 1.6 + 8 * scale
  ctx.font = `600 ${titleSize}px ${FONT}`
  for (const line of titleLines) {
    ctx.fillText(line, left, y + (titleLead - titleSize) / 2)
    y += titleLead
  }
  if (subLines.length) {
    y += 10 * scale
    ctx.globalAlpha = 0.9
    ctx.font = `400 ${subSize}px ${FONT}`
    for (const line of subLines) {
      ctx.fillText(line, left, y + (subLead - subSize) / 2)
      y += subLead
    }
    ctx.globalAlpha = 1
  }

  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('匯出圖卡失敗'))), 'image/png')
    } catch (error) {
      reject(error)
    }
  })
}
