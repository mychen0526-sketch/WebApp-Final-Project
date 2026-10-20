import { useStudio } from '../context.js'

const WEEK = ['一', '二', '三', '四', '五', '六', '日']

export function CalendarPage() {
  const { state, openItem, cancelSchedule } = useStudio()
  const scheduled = state.drafts.filter((item) => item.status === '已排程')
  const cells = Array.from({ length: 35 }, (_, index) => {
    const day = index - 3
    return day > 0 && day <= 31 ? day : null
  })

  return (
    <div className="grid-2">
      <article className="card">
        <h3>2026 年 10 月</h3>
        <p className="sub">只有已排程、還沒發出的內容會出現在這裡。</p>
        <div className="cal">
          {WEEK.map((day) => <i key={day}>{day}</i>)}
          {cells.map((day, index) => {
            const events = day ? scheduled.filter((item) => Number(String(item.when).slice(8, 10)) === day) : []
            return (
              <div key={index} className={day ? `day on${day === 20 ? ' today' : ''}` : 'day'}>
                {day || ''}
                {events.map((item) => <div className="event" key={item.id}>{item.title.slice(0, 10)}</div>)}
              </div>
            )
          })}
        </div>
      </article>
      <article className="card">
        <h3>即將發布</h3>
        <p className="sub">取消排程後，這則回到已核准，資料庫仍保留。</p>
        <div className="list">
          {scheduled.length === 0 ? <p className="meta">目前沒有排程。</p> : null}
          {scheduled.map((item) => (
            <div className="item" key={item.id}>
              <div>
                <b>{item.title}</b>
                <div className="meta">{item.when} · {(item.destinations || []).join('、')}</div>
              </div>
              <div className="row">
                <button className="btn" type="button" onClick={() => openItem(item)}>查看</button>
                <button className="btn" type="button" onClick={() => cancelSchedule(item.id)}>取消排程</button>
              </div>
            </div>
          ))}
        </div>
      </article>
    </div>
  )
}
