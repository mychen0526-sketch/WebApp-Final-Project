import { useState } from 'react'
import { DragCanvas } from '../components/DragCanvas.jsx'
import { Modal } from '../components/ui.jsx'
import { useStudio } from '../context.js'
import { AUDIENCES, layoutPreset, PLATFORM_HINT, PLATFORMS, platformCaption, safetyScan, STAGES, stageEnabled, STYLES, TONES } from '../studio.js'

function StageBar() {
  const { state, goStage } = useStudio()
  return (
    <div className="steps">
      {STAGES.map(([id, label], index) => (
        <button
          key={id}
          type="button"
          className={state.stage === id ? 'on' : ''}
          disabled={!stageEnabled(state, id)}
          onClick={() => goStage(id)}
        >
          0{index + 1} {label}
        </button>
      ))}
    </div>
  )
}

function Canvas({ draggable, compact = false }) {
  const { state, moveLayout } = useStudio()
  const style = STYLES[state.style] || STYLES[0]
  const layout = state.layout ?? layoutPreset('top')
  return (
    <DragCanvas
      style={style}
      company={state.company}
      title={state.title || '尚未寫標題'}
      font={state.font}
      layout={layout}
      compact={compact}
      onLayout={draggable ? moveLayout : undefined}
    />
  )
}

function Preview() {
  const { state, patch } = useStudio()
  return (
    <article className="card">
      <div className="tabs">
        {PLATFORMS.map((name) => (
          <button key={name} type="button" className={state.platform === name ? 'on' : ''} onClick={() => patch({ platform: name })}>{name}</button>
        ))}
      </div>
      <div className="caption">{platformCaption(state.content || '還沒有內文', state.platform)}</div>
      <p className="meta" style={{ marginTop: 8 }}>{PLATFORM_HINT[state.platform]} · 預覽會依平台改長度和開頭</p>
    </article>
  )
}

function WriteStage() {
  const { state, patch, generate, runBatch, openSeries, goStage, startFresh } = useStudio()
  const [count, setCount] = useState(3)
  const series = state.series ?? []

  return (
    <div className="grid-2">
      <article className="card">
        <h3>這篇要講什麼</h3>
        <p className="sub">生成之後，右邊會先顯示大概的樣子。要改位置再去編輯。</p>
        <label className="field">
          主題或貼文方向
          <textarea value={state.prompt} onChange={(event) => patch({ prompt: event.target.value })} />
        </label>
        <div className="row" style={{ marginTop: 12 }}>
          {TONES.map((tone) => (
            <button key={tone} type="button" className={tone === state.tone ? 'tone on' : 'tone'} onClick={() => patch({ tone })}>{tone}</button>
          ))}
          <select value={state.audience} onChange={(event) => patch({ audience: event.target.value })} style={{ width: 'auto' }}>
            {AUDIENCES.map((item) => <option key={item}>{item}</option>)}
          </select>
          <button className="btn primary" type="button" onClick={generate}>生成初稿</button>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <label className="field" style={{ width: 96 }}>
            系列則數
            <input
              type="number"
              min="2"
              max="6"
              value={count}
              onChange={(event) => setCount(Math.max(2, Math.min(6, Number(event.target.value) || 2)))}
            />
          </label>
          <button className="btn soft" type="button" onClick={() => runBatch(count)}>一次生成系列</button>
        </div>
        {series.length > 0 ? (
          <div className="series">
            <p className="meta">點一則，右邊預覽會換成那一則。</p>
            {series.map((item) => (
              <button
                key={item.id}
                type="button"
                className={state.activeId === item.id ? 'series-card on' : 'series-card'}
                onClick={() => openSeries(item)}
              >
                <b>{item.title}</b>
                <span>{item.content.split('\n')[0]}</span>
              </button>
            ))}
          </div>
        ) : null}
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn" type="button" onClick={startFresh}>另開一篇</button>
          <button className="btn primary" type="button" disabled={!state.content.trim()} onClick={() => goStage('edit')}>下一步，去編輯</button>
        </div>
      </article>
      <section className="stack">
        {state.content.trim() ? (
          <>
            <Canvas compact />
            <p className="meta">這是目前這則的大概樣子。位置和字級要到編輯階段才能調。</p>
            <Preview />
          </>
        ) : (
          <article className="card preview-empty">
            <h3>預覽會出現在這裡</h3>
            <p className="sub">生成初稿或一個系列之後，可以先看圖卡和各平台的文字。</p>
          </article>
        )}
        <article className="card">
          <h3>參考來源</h3>
          <p className="sub">先用示範摘要。正式版會改成你訂閱的新聞與研究。</p>
          <div className="list">
            {state.sources.slice(0, 2).map((source) => (
              <div className="item" key={source.title}>
                <div>
                  <b>{source.title}</b>
                  <div className="meta">{source.type} · {source.date}</div>
                </div>
                <span className="tag">{source.origin.split(' · ')[1] || '來源'}</span>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  )
}

function EditStage() {
  const { state, patch, rewrite, saveDraft, submitReview, goStage, moveLayout, remember, applyLocal } = useStudio()
  const [localOpen, setLocalOpen] = useState(false)
  const [localPrompt, setLocalPrompt] = useState('把標題改成更有提問感，並把主色稍微調亮。')

  return (
    <>
      <div className="grid-2">
        <section className="stack">
          <article className="card">
            <h3>文案</h3>
            <p className="sub">這裡只改內容和版面。送交之後就不能再改，要等退回。</p>
            <label className="field">
              圖片標題
              <textarea value={state.title} onChange={(event) => patch({ title: event.target.value })} style={{ minHeight: 72 }} />
            </label>
            <label className="field" style={{ marginTop: 10 }}>
              貼文內文
              <textarea value={state.content} onChange={(event) => patch({ content: event.target.value })} style={{ minHeight: 160 }} />
            </label>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" type="button" onClick={() => rewrite('short')}>改短一點</button>
              <button className="btn" type="button" onClick={() => rewrite('friendly')}>語氣再輕一點</button>
              <button className="btn" type="button" onClick={() => rewrite('new')}>換一個版本</button>
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="meta">這版感覺如何</span>
              {['喜歡', '普通', '不喜歡'].map((rating) => (
                <button key={rating} className="btn" type="button" onClick={() => remember(rating)}>{rating}</button>
              ))}
            </div>
          </article>
          <article className="card">
            <h3>版面</h3>
            <p className="sub">換色、調字，或把圖和文字拖到想要的位置。</p>
            <div className="row" style={{ marginBottom: 12 }}>
              <button className="btn" type="button" onClick={() => moveLayout(layoutPreset('top'))}>圖在上</button>
              <button className="btn" type="button" onClick={() => moveLayout(layoutPreset('bottom'))}>圖在下</button>
            </div>
            <div className="row">
              <div className="swatches">
                {STYLES.map((item, index) => (
                  <button
                    key={item[2]}
                    type="button"
                    className={index === state.style ? 'swatch on' : 'swatch'}
                    style={{ background: `linear-gradient(135deg, ${item[0]}, ${item[1]})` }}
                    title={item[2]}
                    onClick={() => patch({ style: index, themeName: item[2] })}
                  />
                ))}
              </div>
              <label className="row" style={{ color: '#667085', fontSize: 12.5 }}>
                標題字級
                <input type="range" min="24" max="44" value={state.font} onChange={(event) => patch({ font: Number(event.target.value) })} />
              </label>
              <button className="btn soft" type="button" onClick={() => setLocalOpen(true)}>局部調整</button>
            </div>
          </article>
          <div className="row">
            <button className="btn" type="button" onClick={() => goStage('write')}>回到撰寫</button>
            <button className="btn" type="button" onClick={saveDraft}>存成草稿</button>
            <button className="btn primary" type="button" onClick={submitReview}>送交審核</button>
          </div>
        </section>
        <section className="stack">
          <Canvas draggable />
          <Preview />
        </section>
      </div>
      {localOpen ? (
        <Modal
          title="局部調整"
          desc="描述想改的地方。示範版只認得標題、顏色和字級。"
          onClose={() => setLocalOpen(false)}
          actions={<button className="btn primary" type="button" onClick={() => { applyLocal(localPrompt); setLocalOpen(false) }}>套用</button>}
        >
          <textarea value={localPrompt} onChange={(event) => setLocalPrompt(event.target.value)} />
        </Modal>
      ) : null}
    </>
  )
}

function ReviewStage() {
  const { state, approve, returnToDraft } = useStudio()
  const scan = safetyScan(state)
  const [checked, setChecked] = useState({ read: false, rights: false })

  return (
    <div className="grid-2">
      <section className="stack">
        <article className="card">
          <h3>確認這則內容</h3>
          <p className="sub">這是唯一的核准。通過之後才能發布；要改字請退回草稿。</p>
          <div className="caption">{state.title}</div>
          <div className="caption" style={{ marginTop: 8 }}>{state.content}</div>
          <div className={scan.detected.length ? 'notice bad' : 'notice'} style={{ marginTop: 12 }}>{scan.risks}</div>
          <label className="check" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={checked.read} onChange={(event) => setChecked((value) => ({ ...value, read: event.target.checked }))} />
            我已讀過全文，確認可以對外發布
          </label>
          <label className="check" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={checked.rights} onChange={(event) => setChecked((value) => ({ ...value, rights: event.target.checked }))} />
            圖片與文字都有使用權利
          </label>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn" type="button" onClick={() => returnToDraft(state.activeId)}>退回修改</button>
            <button className="btn primary" type="button" disabled={!(checked.read && checked.rights)} onClick={approve}>核准</button>
          </div>
        </article>
      </section>
      <section className="stack">
        <Canvas />
        <Preview />
      </section>
    </div>
  )
}

function PublishStage() {
  const { state, publish, cancelSchedule, returnToDraft, togglePlatform } = useStudio()
  const [when, setWhen] = useState('2026-10-21T09:00')
  const item = state.drafts.find((draft) => draft.id === state.activeId)
  const status = item?.status

  return (
    <div className="grid-2">
      <section className="stack">
        <article className="card">
          <h3>發布</h3>
          {status === '已發布' ? <p className="sub">這則已經發布，只留紀錄，不能再改也不能刪。</p> : null}
          {status === '已排程' ? <p className="sub">已排在 {item.when}。取消後會回到已核准，不會從資料庫消失。</p> : null}
          {status === '已核准' ? <p className="sub">審核已通過。可以直接發，或排一個以後的時間。</p> : null}
          <div className="checks">
            {PLATFORMS.map((name) => (
              <label className="check" key={name}>
                <input type="checkbox" checked={state.platforms.includes(name)} disabled={status !== '已核准'} onChange={() => togglePlatform(name)} />
                {name}
              </label>
            ))}
          </div>
          {status === '已核准' ? (
            <>
              <label className="field" style={{ marginTop: 14 }}>
                排程時間
                <input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
              </label>
              <div className="row" style={{ marginTop: 14 }}>
                <button className="btn" type="button" onClick={() => returnToDraft(item.id)}>退回修改</button>
                <button className="btn" type="button" onClick={() => publish(item.id, when)}>排程發布</button>
                <button className="btn primary" type="button" onClick={() => publish(item.id, '現在')}>直接發布</button>
              </div>
            </>
          ) : null}
          {status === '已排程' ? (
            <div className="row" style={{ marginTop: 14 }}>
              <button className="btn" type="button" onClick={() => cancelSchedule(item.id)}>取消排程</button>
            </div>
          ) : null}
          {item?.destinations?.length ? <p className="meta" style={{ marginTop: 12 }}>目的地：{item.destinations.join('、')}</p> : null}
        </article>
      </section>
      <section className="stack">
        <Canvas />
        <Preview />
      </section>
    </div>
  )
}

export function WorkspacePage() {
  const { state } = useStudio()
  const stage = state.stage || 'write'
  return (
    <>
      <StageBar />
      {stage === 'write' ? <WriteStage /> : null}
      {stage === 'edit' ? <EditStage /> : null}
      {stage === 'review' ? <ReviewStage /> : null}
      {stage === 'publish' ? <PublishStage /> : null}
    </>
  )
}
