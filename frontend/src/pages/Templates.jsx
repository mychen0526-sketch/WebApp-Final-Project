import { useState } from 'react'
import { useStudio } from '../context.js'
import { STYLES, TONES } from '../studio.js'

export function TemplatesPage() {
  const { state, patch, applyTemplate } = useStudio()
  const [tone, setTone] = useState(state.tone)

  return (
    <div className="stack">
      <article className="card">
        <h3>品牌設定</h3>
        <p className="sub">名稱會出現在圖卡角落，預設語氣會跟著版型一起套用。</p>
        <div className="row">
          <label className="field" style={{ flex: 1 }}>
            品牌名稱
            <input value={state.company} onChange={(event) => patch({ company: event.target.value })} />
          </label>
          <label className="field" style={{ width: 220 }}>
            預設語氣
            <select value={tone} onChange={(event) => setTone(event.target.value)}>
              {TONES.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        </div>
      </article>
      <div className="grid-4">
        {STYLES.map((item, index) => (
          <article className="card" key={item[2]}>
            <div style={{ height: 120, borderRadius: 14, background: `linear-gradient(145deg, ${item[0]}, ${item[1]})` }} />
            <h3 style={{ marginTop: 12 }}>{item[2]}</h3>
            <p className="sub">適合 {tone} 的圖卡底。</p>
            <button className="btn soft" onClick={() => applyTemplate(index, tone)}>套用到工作台</button>
          </article>
        ))}
      </div>
    </div>
  )
}
