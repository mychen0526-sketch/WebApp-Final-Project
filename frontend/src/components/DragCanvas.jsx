import { useRef } from 'react'

function clamp(value) {
  return Math.min(86, Math.max(14, value))
}

function DragBlock({ pos, label, onMove, draggable, children }) {
  const last = useRef(null)

  function pointerDown(event) {
    if (!draggable) return
    event.currentTarget.setPointerCapture(event.pointerId)
    last.current = { x: event.clientX, y: event.clientY, pos: { ...pos } }
  }

  function pointerMove(event) {
    if (!last.current) return
    const board = event.currentTarget.closest('.artboard')
    const rect = board.getBoundingClientRect()
    const x = clamp(last.current.pos.x + ((event.clientX - last.current.x) / rect.width) * 100)
    const y = clamp(last.current.pos.y + ((event.clientY - last.current.y) / rect.height) * 100)
    onMove({ x, y })
  }

  function pointerUp() {
    last.current = null
  }

  return (
    <div
      className={draggable ? 'float-block' : 'float-block is-locked'}
      style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
    >
      {draggable ? <span className="drag-label">{label}</span> : null}
      {children}
    </div>
  )
}

export function DragCanvas({ style, company, title, subtitle = '', font, layout, onLayout, compact = false, background = null }) {
  const draggable = Boolean(onLayout)
  const vars = { '--a': style[0], '--b': style[1], '--size': `${font}px` }
  if (background) vars.backgroundImage = `url("${background}")`
  return (
    <article className={`artboard is-free${compact ? ' is-compact' : ''}${background ? ' has-template' : ''}`} style={vars}>
      {background ? null : (
        <DragBlock draggable={draggable} pos={layout.image} label="拖曳圖形" onMove={(image) => onLayout?.({ ...layout, image })}>
          <div className="art-shape" />
        </DragBlock>
      )}
      <DragBlock draggable={draggable} pos={layout.text} label="拖曳文字" onMove={(text) => onLayout?.({ ...layout, text })}>
        <p className="art-kicker">{company}</p>
        <p className="art-display">{title}</p>
        {subtitle ? <p className="art-sub">{subtitle}</p> : null}
      </DragBlock>
      <footer>
        <span>{draggable ? (background ? '拖曳文字到圖片空白處' : '拖曳圖形或文字') : '預覽'}</span>
        <span>1080 × 1080</span>
      </footer>
    </article>
  )
}
