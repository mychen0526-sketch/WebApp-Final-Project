import { useState } from 'react'
import { Modal } from '../components/ui.jsx'
import { useStudio } from '../context.js'

export function DiscoverPage() {
  const { state, addSource, useSource } = useStudio()
  const [url, setUrl] = useState('')
  const [picked, setPicked] = useState(null)

  return (
    <>
      <div className="grid-4" style={{ marginBottom: 14 }}>
        {[
          ['今日候選', state.sources.length],
          ['可信來源', state.sources.length],
          ['已採用', state.drafts.length],
          ['待查證', 0],
        ].map(([label, value]) => (
          <article className="card stat" key={label}>
            <span>{label}</span>
            <b>{value}</b>
          </article>
        ))}
      </div>
      <div className="grid-2">
        <article className="card">
          <h3>情報列表</h3>
          <p className="sub">點開可以看摘要，或直接拿去寫稿。</p>
          <div className="list">
            {state.sources.map((source) => (
              <div className="item" key={source.title}>
                <div>
                  <b>{source.title}</b>
                  <div className="meta">{source.type} · {source.origin} · {source.date}</div>
                </div>
                <div className="row">
                  <button className="btn" onClick={() => setPicked(source)}>查看</button>
                  <button className="btn soft" onClick={() => useSource(source)}>用來寫稿</button>
                </div>
              </div>
            ))}
          </div>
        </article>
        <article className="card">
          <h3>加入來源</h3>
          <p className="sub">貼上網站或 RSS。現在只會存成示範摘要。</p>
          <label className="field">
            網址
            <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/feed" />
          </label>
          <button className="btn primary" style={{ marginTop: 12 }} onClick={() => { addSource(url); setUrl('') }}>加入</button>
          <p className="notice" style={{ marginTop: 14 }}>來源可信度仍需人工判斷。這裡不會自動判定新聞真偽。</p>
        </article>
      </div>
      {picked ? (
        <Modal
          title={picked.title}
          desc={`${picked.type} · ${picked.origin} · ${picked.date}`}
          onClose={() => setPicked(null)}
          actions={<button className="btn primary" onClick={() => { useSource(picked); setPicked(null) }}>用來寫稿</button>}
        >
          <p>{picked.summary}</p>
        </Modal>
      ) : null}
    </>
  )
}
