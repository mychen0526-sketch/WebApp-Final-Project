import { useStudio } from '../context.js'

export function ReviewPage() {
  const { state, openItem, returnToDraft } = useStudio()
  const queue = state.drafts.filter((item) => item.status === '待審核')

  return (
    <article className="card">
      <h3>待你確認</h3>
      <p className="sub">已送審、尚未核准的貼文。打開後再核准一次。</p>
      <div className="list">
        {queue.length === 0 ? <p className="meta">目前沒有待審內容。</p> : null}
        {queue.map((item) => (
          <div className="item" key={item.id}>
            <div>
              <b>{item.title}</b>
              <div className="meta">{item.date} · {item.content.slice(0, 42)}</div>
            </div>
            <div className="row">
              <span className="tag amber">待審核</span>
              <button className="btn primary" type="button" onClick={() => openItem(item)}>前往審核</button>
              <button className="btn" type="button" onClick={() => returnToDraft(item.id)}>退回修改</button>
            </div>
          </div>
        ))}
      </div>
    </article>
  )
}
