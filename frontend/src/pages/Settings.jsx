import { useState } from 'react'
import { useStudio } from '../context.js'
import { isRealPlatform, PLATFORM_NAME } from '../lib/posts.js'
import { PLATFORMS } from '../studio.js'

function Accounts() {
  const { state, connectAccount, disconnectAccount, refreshAccounts } = useStudio()
  return (
    <article className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3>已連接的平台</h3>
        <button className="btn" type="button" onClick={refreshAccounts}>重新整理</button>
      </div>
      <p className="sub">連結會跳到官方授權頁（要先開 ngrok）。授權碼只存在後端，前端拿不到。</p>
      <div className="list">
        {state.accounts.map((account) => (
          <div className="item" key={account.platform}>
            <div>
              <b>{PLATFORM_NAME[account.platform]}</b>
              <div className="meta">
                {account.connected
                  ? `@${account.username || '已連結'}${account.expired ? ' · 授權已過期' : account.token_expires_at ? ` · 到期 ${account.token_expires_at.slice(0, 10)}` : ''}`
                  : '尚未連結'}
              </div>
            </div>
            <div className="row">
              {account.connected && !account.expired ? <span className="tag green">已連結</span> : null}
              <button className={account.connected && !account.expired ? 'btn' : 'btn primary'} type="button" onClick={() => connectAccount(account.platform)}>
                {account.connected ? '重新連結' : '連結'}
              </button>
              {account.connected ? <button className="btn" type="button" onClick={() => disconnectAccount(account.platform)}>解除</button> : null}
            </div>
          </div>
        ))}
        {['X', 'Telegram'].map((name) => (
          <div className="item" key={name}>
            <div>
              <b>{name}</b>
              <div className="meta">示範平台，後端尚未串接</div>
            </div>
            <span className="tag">示範</span>
          </div>
        ))}
      </div>
    </article>
  )
}

export function SettingsPage() {
  const { state, patch, addWord, removeWord, togglePlatform, saveProfile } = useStudio()
  const [word, setWord] = useState('')

  return (
    <div className="grid-2">
      <section className="stack">
        <article className="card">
          <h3>寫作偏好</h3>
          <p className="sub">存在後端，下次登入會沿用。</p>
          <label className="field">
            常用語氣
            <input value={state.tone} onChange={(event) => patch({ tone: event.target.value })} />
          </label>
          <label className="field" style={{ marginTop: 10 }}>
            主要受眾
            <input value={state.audience} onChange={(event) => patch({ audience: event.target.value })} />
          </label>
          <button className="btn primary" type="button" style={{ marginTop: 12 }} onClick={saveProfile}>儲存偏好</button>
        </article>
        <article className="card">
          <h3>最近的回饋</h3>
          <p className="sub">在工作台按喜歡、普通或不喜歡之後，會記在這裡，也會存到後端。</p>
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
        <Accounts />
        <article className="card">
          <h3>預設發布目的地</h3>
          <p className="sub">送審時會帶這些平台。X、Telegram 只會出現在預覽。</p>
          <div className="checks">
            {PLATFORMS.map((name) => (
              <label className="check" key={name}>
                <input type="checkbox" checked={state.platforms.includes(name)} onChange={() => togglePlatform(name)} />
                {name}{isRealPlatform(name) ? '' : '（示範）'}
              </label>
            ))}
          </div>
        </article>
        <article className="card">
          <h3>敏感詞</h3>
          <p className="sub">文案、標題或圖卡文字出現這些詞時，後端會擋下發布與排程。</p>
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
