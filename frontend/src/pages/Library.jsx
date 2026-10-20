import { useState } from 'react'
import { Modal } from '../components/ui.jsx'
import { useStudio } from '../context.js'

const FILTERS = ['全部', '草稿', '待審核', '已核准', '已排程', '已發布']

function tagClass(status) {
  if (status === '已發布' || status === '已核准') return 'tag green'
  if (status === '待審核' || status === '已排程') return 'tag amber'
  return 'tag'
}

export function LibraryPage() {
  const { state, openItem, deleteDraft, publish, cancelSchedule, returnToDraft } = useStudio()
  const [filter, setFilter] = useState('全部')
  const [scheduling, setScheduling] = useState(null)
  const [when, setWhen] = useState('2026-10-21T09:00')
  const items = state.drafts.filter((item) => filter === '全部' || item.status === filter)

  return (
    <>
      <article className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div>
            <h3>全部內容</h3>
            <p className="sub">草稿可以改、可以刪。送審之後只能審核、發布或取消排程。</p>
          </div>
          <div className="row">
            {FILTERS.map((item) => (
              <button key={item} type="button" className={item === filter ? 'tone on' : 'tone'} onClick={() => setFilter(item)}>{item}</button>
            ))}
          </div>
        </div>
        <div className="list">
          {items.length === 0 ? <p className="meta">這個狀態目前沒有內容。</p> : null}
          {items.map((item) => (
            <div className="item" key={item.id}>
              <div>
                <b>{item.title}</b>
                <div className="meta">{item.date} · {item.content.slice(0, 36)}{item.when ? ` · ${item.when}` : ''}</div>
              </div>
              <div className="row">
                <span className={tagClass(item.status)}>{item.status}</span>
                {item.status === '草稿' ? (
                  <>
                    <button className="btn" type="button" onClick={() => openItem(item)}>繼續編輯</button>
                    <button className="btn" type="button" onClick={() => deleteDraft(item.id)}>刪除</button>
                  </>
                ) : null}
                {item.status === '待審核' ? (
                  <>
                    <button className="btn" type="button" onClick={() => openItem(item)}>前往審核</button>
                    <button className="btn" type="button" onClick={() => returnToDraft(item.id)}>退回修改</button>
                  </>
                ) : null}
                {item.status === '已核准' ? (
                  <>
                    <button className="btn primary" type="button" onClick={() => publish(item.id, '現在')}>直接發布</button>
                    <button className="btn" type="button" onClick={() => { setWhen('2026-10-21T09:00'); setScheduling(item) }}>排程發布</button>
                    <button className="btn" type="button" onClick={() => returnToDraft(item.id)}>退回修改</button>
                  </>
                ) : null}
                {item.status === '已排程' ? (
                  <>
                    <button className="btn" type="button" onClick={() => openItem(item)}>查看</button>
                    <button className="btn" type="button" onClick={() => cancelSchedule(item.id)}>取消排程</button>
                  </>
                ) : null}
                {item.status === '已發布' ? (
                  <button className="btn" type="button" onClick={() => openItem(item)}>查看</button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </article>
      {scheduling ? (
        <Modal
          title="排程發布"
          desc={scheduling.title}
          onClose={() => setScheduling(null)}
          actions={<button className="btn primary" type="button" onClick={() => { if (publish(scheduling.id, when)) setScheduling(null) }}>加入排程</button>}
        >
          <label className="field">
            排程時間
            <input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
          </label>
        </Modal>
      ) : null}
    </>
  )
}
