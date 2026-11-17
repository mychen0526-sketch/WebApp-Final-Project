import { useState } from 'react'
import { useStudio } from '../context.js'

const WEEK = ['一', '二', '三', '四', '五', '六', '日']

export function CalendarPage() {
  const { state, openItem, cancelSchedule } = useStudio()
  const today = new Date()
  const [month, setMonth] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1))
  const scheduled = state.drafts
    .filter((item) => item.status === '已排程' && item.scheduledAt)
    .sort((a, b) => new Date(a.scheduledAt) - new Date(b.scheduledAt))
  const year = month.getFullYear()
  const m = month.getMonth()
  const lead = (month.getDay() + 6) % 7 // Monday first
  const days = new Date(year, m + 1, 0).getDate()
  const cells = Array.from({ length: Math.ceil((lead + days) / 7) * 7 }, (_, index) => {
    const day = index - lead + 1
    return day > 0 && day <= days ? day : null
  })
  const sameDay = (iso, day) => {
    const d = new Date(iso)
    return d.getFullYear() === year && d.getMonth() === m && d.getDate() === day
  }
  const isToday = (day) => today.getFullYear() === year && today.getMonth() === m && today.getDate() === day

  return (
    <div className="grid-2">
      <article className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>{year} 年 {m + 1} 月</h3>
          <div className="row">
            <button className="btn" type="button" onClick={() => setMonth(new Date(year, m - 1, 1))}>‹</button>
            <button className="btn" type="button" onClick={() => setMonth(new Date(year, m + 1, 1))}>›</button>
          </div>
        </div>
        <p className="sub">只有已排程、還沒發出的內容會出現在這裡。時間到時後端排程器會自動發布。</p>
        <div className="cal">
          {WEEK.map((day) => <i key={day}>{day}</i>)}
          {cells.map((day, index) => {
            const events = day ? scheduled.filter((item) => sameDay(item.scheduledAt, day)) : []
            return (
              <div key={index} className={day ? `day on${isToday(day) ? ' today' : ''}` : 'day'}>
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
