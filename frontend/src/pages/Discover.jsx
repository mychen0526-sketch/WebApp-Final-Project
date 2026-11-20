import { useState } from 'react'
import { Modal } from '../components/ui.jsx'
import { useStudio } from '../context.js'

const BACKEND_LABEL = { tavily: 'Tavily 新聞搜尋', rss: 'Bing 新聞 RSS（示範用）', mock: '示範資料' }

// One search result: the publisher's lead picture, headline, source and date.
export function NewsCard({ item, onOpen, onUse, compact = false, selected = false }) {
  return (
    <article className={`news-card${compact ? ' is-compact' : ''}${selected ? ' on' : ''}`}>
      <button type="button" className="news-thumb" onClick={() => onOpen?.(item)} aria-label={`查看 ${item.title}`}>
        {item.image_url ? <img src={item.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span>沒有圖片</span>}
      </button>
      <div className="news-body">
        <b className="news-title">{item.title}</b>
        <span className="meta">{[item.source, item.published].filter(Boolean).join(' · ')}</span>
        <div className="row news-actions">
          {item.image_url ? (
            <>
              <button className="btn primary" type="button" onClick={() => onUse(item, 'photo')}>用這張圖寫稿</button>
              {compact ? null : <button className="btn" type="button" onClick={() => onUse(item, 'blend')}>AI 融合</button>}
            </>
          ) : null}
          <button className={item.image_url ? 'btn' : 'btn primary'} type="button" onClick={() => onUse(item, 'ai')}>只用內容</button>
        </div>
      </div>
    </article>
  )
}

export function DiscoverPage() {
  const { state, patch, searchNews, useSource } = useStudio()
  const { research } = state
  const [picked, setPicked] = useState(null)
  const withImages = research.results.filter((item) => item.image_url).length

  const submit = (event) => {
    event.preventDefault()
    searchNews(research.query)
  }

  return (
    <>
      <article className="card" style={{ marginBottom: 14 }}>
        <form className="row search-row" onSubmit={submit}>
          <input
            value={research.query}
            onChange={(event) => patch({ research: { ...research, query: event.target.value } })}
            placeholder="搜尋新聞或產業趨勢，例如：AI 新創 商業化"
            aria-label="搜尋關鍵字"
          />
          <button className="btn primary" type="submit" disabled={research.loading}>{research.loading ? '搜尋中…' : '搜尋'}</button>
        </form>
        <p className="meta" style={{ marginTop: 8 }}>
          {research.backend ? `來源：${BACKEND_LABEL[research.backend] || research.backend} · ` : ''}
          圖片取自原始媒體的分享圖（og:image），圖卡上會標註出處。
        </p>
      </article>

      {research.results.length ? (
        <>
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <h3>「{research.query}」的結果</h3>
            <span className="meta">{research.results.length} 則 · {withImages} 則有圖片</span>
          </div>
          <div className="news-grid">
            {research.results.map((item) => (
              <NewsCard key={item.url} item={item} onOpen={setPicked} onUse={useSource} />
            ))}
          </div>
        </>
      ) : (
        <article className="preview-empty">
          <h3>{research.loading ? '搜尋中…' : '還沒有搜尋'}</h3>
          <p className="sub">找到的新聞可以直接拿來寫稿；有圖片的可以放進圖卡，或用 AI 融合成品牌風格。</p>
          {research.error ? <p className="notice bad">{research.error}</p> : null}
        </article>
      )}

      <p className="notice" style={{ marginTop: 14 }}>
        新聞照片多半有著作權。直接使用原圖前請確認授權；不確定時改用「AI 融合」或「只用內容」。來源可信度仍需人工判斷。
      </p>

      {picked ? (
        <Modal
          title={picked.title}
          desc={[picked.source, picked.published].filter(Boolean).join(' · ')}
          onClose={() => setPicked(null)}
          actions={(
            <>
              <a className="btn" href={picked.url} target="_blank" rel="noreferrer">開啟原文</a>
              <button className="btn primary" type="button" onClick={() => { useSource(picked); setPicked(null) }}>用來寫稿</button>
            </>
          )}
        >
          {picked.image_url ? <img className="news-hero" src={picked.image_url} alt="" referrerPolicy="no-referrer" /> : null}
          <p>{picked.summary || '這則沒有摘要，可開啟原文查看。'}</p>
        </Modal>
      ) : null}
    </>
  )
}
