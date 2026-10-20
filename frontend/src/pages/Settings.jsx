import { useState } from 'react'
import { useStudio } from '../context.js'
import { PLATFORMS } from '../studio.js'

export function SettingsPage() {
  const { state, patch, addWord, removeWord, togglePlatform } = useStudio()
  const [word, setWord] = useState('')

  return (
    <div className="grid-2">
      <section className="stack">
        <article className="card">
          <h3>寫作偏好</h3>
          <p className="sub">這些會留在這次示範裡，重新整理頁面後會回到預設。</p>
          <label className="field">
            常用語氣
            <input value={state.tone} onChange={(event) => patch({ tone: event.target.value })} />
          </label>
          <label className="field" style={{ marginTop: 10 }}>
            主要受眾
            <input value={state.audience} onChange={(event) => patch({ audience: event.target.value })} />
          </label>
        </article>
        <article className="card">
          <h3>最近的回饋</h3>
          <p className="sub">在工作台按喜歡、普通或不喜歡之後，會記在這裡。</p>
          <div className="list">
            {state.feedback.length === 0 ? <p className="meta">還沒有回饋。</p> : null}
            {state.feedback.map((item, index) => (
              <div className="item" key={`${item.time}-${index}`}>
                <div>
                  <b>{item.rating}</b>
                  <div className="meta">{item.text}</div>
                </div>
                <span className="meta">{item.time}</span>
              </div>
            ))}
          </div>
        </article>
      </section>
      <section className="stack">
        <article className="card">
          <h3>已連接的平台</h3>
          <p className="sub">勾選代表這次示範要發去哪裡，尚未真正登入帳號。</p>
          <div className="checks">
            {PLATFORMS.map((name) => (
              <label className="check" key={name}>
                <input type="checkbox" checked={state.platforms.includes(name)} onChange={() => togglePlatform(name)} />
                {name}
              </label>
            ))}
          </div>
        </article>
        <article className="card">
          <h3>敏感詞</h3>
          <p className="sub">文案或標題出現這些詞時，安全檢查會擋下發布。</p>
          <div className="row">
            {state.sensitive.map((item) => (
              <button key={item} className="tone" onClick={() => removeWord(item)}>{item} ×</button>
            ))}
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <input value={word} onChange={(event) => setWord(event.target.value)} placeholder="新增一個詞" />
            <button className="btn" onClick={() => { addWord(word); setWord('') }}>加入</button>
          </div>
          <p className="notice" style={{ marginTop: 14 }}>人工審核不能關閉。就算沒有敏感詞，也要先核准才能發布。</p>
        </article>
      </section>
    </div>
  )
}
