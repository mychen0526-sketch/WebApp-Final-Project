import { useRef, useState } from 'react'
import { useStudio } from '../context.js'
import { STYLES, TONES } from '../studio.js'

export function TemplatesPage() {
  const { state, patch, applyTemplate, addTemplate, removeTemplate, pickTemplate, saveProfile } = useStudio()
  const [tone, setTone] = useState(state.tone)
  const [name, setName] = useState('')
  const fileRef = useRef(null)

  function upload(event) {
    const file = event.target.files?.[0]
    addTemplate(file, name)
    setName('')
    event.target.value = ''
  }

  return (
    <div className="stack">
      <article className="card">
        <h3>品牌設定</h3>
        <p className="sub">名稱會出現在圖卡角落，預設語氣會跟著版型一起套用。</p>
        <div className="row">
          <label className="field" style={{ flex: 1 }}>
            品牌名稱
            <input value={state.company} onChange={(event) => patch({ company: event.target.value })} onBlur={saveProfile} />
          </label>
          <label className="field" style={{ width: 220 }}>
            預設語氣
            <select value={tone} onChange={(event) => setTone(event.target.value)}>
              {TONES.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        </div>
      </article>

      <article className="card">
        <h3>我的圖片模板</h3>
        <p className="sub">上傳自己做好的底圖（PNG 或 JPEG，8 MB 內，建議 1080×1080）。套用後圖卡用這張當背景，AI 只寫文字、不再產底圖。</p>
        <div className="row">
          <label className="field" style={{ flex: 1 }}>
            模板名稱（可不填）
            <input value={name} placeholder="例如：週報封面" onChange={(event) => setName(event.target.value)} />
          </label>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg" hidden onChange={upload} />
          <button className="btn primary" type="button" onClick={() => fileRef.current?.click()}>上傳圖片模板</button>
        </div>
        {state.templates.length ? (
          <div className="grid-4" style={{ marginTop: 14 }}>
            {state.templates.map((item) => (
              <div key={item.id} className="stack" style={{ gap: 8 }}>
                <div className="template-thumb" style={{ backgroundImage: `url("${item.url}")`, boxShadow: item.id === state.templateId ? '0 0 0 2px var(--accent)' : 'none' }} />
                <b style={{ fontSize: 13.5 }}>{item.name}</b>
                <div className="row">
                  <button className="btn soft" type="button" onClick={() => pickTemplate(item.id)}>
                    {item.id === state.templateId ? '使用中' : '套用到工作台'}
                  </button>
                  <button className="btn" type="button" onClick={() => removeTemplate(item.id)}>移除</button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="meta" style={{ marginTop: 12 }}>還沒有模板。沒上傳時，圖卡用下面四種配色。</p>
        )}
      </article>

      <div className="grid-4">
        {STYLES.map((item, index) => (
          <article className="surface" key={item[2]}>
            <div style={{ height: 120, borderRadius: 10, background: `linear-gradient(145deg, ${item[0]}, ${item[1]})` }} />
            <h3 style={{ marginTop: 12 }}>{item[2]}</h3>
            <p className="sub">套用為圖卡底色</p>
            <button className="btn soft" onClick={() => applyTemplate(index, tone)}>套用到工作台</button>
          </article>
        ))}
      </div>
    </div>
  )
}
