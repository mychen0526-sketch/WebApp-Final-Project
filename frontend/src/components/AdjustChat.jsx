import { useEffect, useRef, useState } from 'react'
import { useStudio } from '../context.js'
import { isAbort } from '../lib/api.js'
import { STYLES } from '../studio.js'

const SUGGESTIONS = ['標題改成問句', '整篇改短一點', '換一個配色', '標題字放大']

const clip = (text, n = 22) => {
  const flat = (text || '').replaceAll('\n', ' ')
  return flat.length > n ? `${flat.slice(0, n)}…` : flat
}

// One line per field the AI wants to change, old → new.
function describe(changes, was) {
  const lines = []
  if (changes.title !== undefined) lines.push(`標題：「${clip(was.title)}」→「${clip(changes.title)}」`)
  if (changes.subtitle !== undefined) lines.push(`副標：「${clip(was.subtitle)}」→「${clip(changes.subtitle)}」`)
  if (changes.threads !== undefined) lines.push(`Threads 文案：改寫（${[...was.content].length} → ${[...changes.threads].length} 字）`)
  if (changes.instagram !== undefined) lines.push(`IG 文案：改寫（${[...changes.instagram].length} 字）`)
  if (changes.linkedin !== undefined) lines.push(`LinkedIn 文案：改寫（${[...changes.linkedin].length} 字）`)
  if (changes.style !== undefined) lines.push(`配色：${STYLES[was.style]?.[2]} → ${STYLES[changes.style]?.[2]}`)
  if (changes.font !== undefined) lines.push(`標題字級：${was.font} → ${changes.font}`)
  return lines
}

/**
 * AI 微調: ask for a change in words; each AI reply lists what it would change and waits for
 * 套用 / 略過. Applied turns can be undone (last applied first). Nothing is saved until 存成草稿 / 送審.
 */
export function AdjustChat() {
  const { state, adjust, applyChanges, patch, notify } = useStudio()
  const [turns, setTurns] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const abortRef = useRef(null)
  const listRef = useRef(null)
  const locked = Boolean(state.busy)

  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [turns, pending])

  useEffect(() => () => abortRef.current?.abort(), [])

  const setTurn = (index, changes) => setTurns((list) => list.map((turn, i) => (i === index ? { ...turn, ...changes } : turn)))

  // BUG-16: only the most recently applied turn can be undone (stack order).
  const lastAppliedIndex = (() => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      if (turns[i].status === 'applied') return i
    }
    return -1
  })()

  async function send(text) {
    const instruction = text.trim()
    if (!instruction || pending || locked) return
    const history = turns.filter((turn) => !turn.error).slice(-8).map(({ role, text: said }) => ({ role, text: said }))
    const was = { title: state.title, subtitle: state.subtitle, content: state.content, style: state.style, font: state.font }
    setTurns((list) => [...list, { role: 'user', text: instruction }])
    setDraft('')
    const controller = new AbortController()
    abortRef.current = controller
    setPending(true)
    try {
      const result = await adjust(instruction, history, controller.signal)
      if (!result) return
      const { reply, ...changes } = result
      const lines = describe(changes, was)
      setTurns((list) => [...list, { role: 'assistant', text: reply, changes, lines, status: lines.length ? 'pending' : 'none' }])
    } catch (error) {
      const text = isAbort(error) ? '已停止。' : `沒有完成：${error.message}`
      setTurns((list) => [...list, { role: 'assistant', text, error: true }])
    } finally {
      abortRef.current = null
      setPending(false)
    }
  }

  function undo(index) {
    if (locked) return
    if (index !== lastAppliedIndex) {
      notify('請先復原較新的調整', '要從最後一次套用的開始往回復原，才會回到原本的樣子。')
      return
    }
    const turn = turns[index]
    if (!turn?.before) return
    patch(turn.before)
    setTurn(index, { status: 'undone' })
  }

  function onKeyDown(event) {
    // Enter sends; Shift+Enter is a new line; never send while an IME is composing (注音 / 倉頡)
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    send(draft)
  }

  return (
    <article className="surface chat">
      <div className="chat-head">
        <h3>AI 微調</h3>
        <span className="meta">說想改哪裡，確認後才會套用</span>
      </div>
      <div className="chat-list" ref={listRef} aria-live="polite">
        {turns.map((turn, index) => (
          <div key={index} className={`bubble ${turn.role}${turn.error ? ' error' : ''}`}>
            <p>{turn.text}</p>
            {turn.lines?.length ? (
              <ul className="chat-changes">
                {turn.lines.map((line) => <li key={line}>{line}</li>)}
              </ul>
            ) : null}
            {turn.status === 'pending' ? (
              <div className="row chat-actions">
                <button className="btn primary" type="button" disabled={locked} onClick={() => setTurn(index, { status: 'applied', before: applyChanges(turn.changes) })}>套用</button>
                <button className="btn" type="button" onClick={() => setTurn(index, { status: 'skipped' })}>略過</button>
              </div>
            ) : null}
            {turn.status === 'applied' ? (
              <div className="row chat-actions">
                <span className="tag green">已套用</span>
                {index === lastAppliedIndex ? (
                  <button className="link" type="button" disabled={locked} onClick={() => undo(index)}>復原</button>
                ) : (
                  <span className="meta">先復原較新的</span>
                )}
              </div>
            ) : null}
            {turn.status === 'skipped' ? <span className="meta">已略過</span> : null}
            {turn.status === 'undone' ? <span className="meta">已復原</span> : null}
          </div>
        ))}
        {pending ? (
          <div className="bubble assistant thinking">
            <span className="spinner" /> 思考中…
            <button className="link" type="button" onClick={() => abortRef.current?.abort()}>停止</button>
          </div>
        ) : null}
      </div>
      {/* BUG-14: keep suggestions above the input so they stay after the first ask. */}
      <div className="chat-suggest">
        {SUGGESTIONS.map((text) => (
          <button key={text} type="button" className="tone" disabled={locked || pending} onClick={() => send(text)}>{text}</button>
        ))}
      </div>
      <div className="chat-input">
        <textarea
          rows={2}
          value={draft}
          disabled={locked}
          placeholder="例如：標題更有提問感、IG 版多一點 emoji"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button className="btn primary" type="button" disabled={pending || locked || !draft.trim()} onClick={() => send(draft)}>送出</button>
      </div>
    </article>
  )
}
