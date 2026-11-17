import { useState } from 'react'
import { DragCanvas } from '../components/DragCanvas.jsx'
import { Modal } from '../components/ui.jsx'
import { useStudio } from '../context.js'
import { defaultScheduleInput, isRealPlatform, PLATFORM_NAME } from '../lib/posts.js'
import { activeDraft, AUDIENCES, cardBackground, layoutPreset, PLATFORM_HINT, PLATFORMS, platformCaption, safetyScan, STAGES, stageEnabled, STYLES, TONES } from '../studio.js'

const THREADS_LIMIT = 500
const BUSY_TEXT = {
  candidates: 'AI 正在想 3 個方向…',
  generating: 'AI 正在寫文案、產生圖卡（約 20–60 秒）…',
  series: '正在生成系列…',
  saving: '儲存中…',
  submitting: '匯出圖卡並送審中…',
  publishing: '發布中…',
}

function Busy() {
  const { state } = useStudio()
  if (!state.busy) return null
  return (
    <p className="notice busy" style={{ marginTop: 12 }}>
      <span className="spinner" />
      {BUSY_TEXT[state.busy] || '處理中…'}
    </p>
  )
}

function StageBar() {
  const { state, goStage, startFresh } = useStudio()
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
      {state.activeId ? (
        <button type="button" className="new-post" disabled={Boolean(state.busy)} onClick={startFresh}>＋ 寫新的一篇</button>
      ) : null}
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
      subtitle={state.subtitle}
      font={state.font}
      layout={layout}
      compact={compact}
      background={cardBackground(state)}
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
      <div className="caption">{platformCaption(state, state.platform) || '還沒有內文'}</div>
      <p className="meta" style={{ marginTop: 8 }}>{PLATFORM_HINT[state.platform]}</p>
    </article>
  )
}

function Candidates() {
  const { state, pickCandidate } = useStudio()
  if (!state.candidates.length) return null
  return (
    <div className="candidates">
      <p className="meta">AI 提出的 3 個方向，挑一個開始生成：</p>
      {state.candidates.map((item) => (
        <button key={item.title} type="button" className="candidate" disabled={Boolean(state.busy)} onClick={() => pickCandidate(item)}>
          <b>{item.title}</b>
          <span>{item.angle}</span>
          <span>開頭：{item.hook}</span>
        </button>
      ))}
    </div>
  )
}

function WriteStage() {
  const { state, patch, generate, runBatch, openSeries, goStage, startFresh } = useStudio()
  const [count, setCount] = useState(3)
  const series = state.series.map((id) => state.drafts.find((item) => item.id === id)).filter(Boolean)
  const active = activeDraft(state)

  return (
    <div className="grid-2">
      <article className="card">
        <h3>這篇要講什麼</h3>
        <p className="sub">輸入目標 → AI 提出 3 個方向 → 挑一個 → AI 寫兩個平台的文案並產生圖卡。</p>
        <label className="field">
          主題或貼文方向
          <textarea value={state.prompt} onChange={(event) => patch({ prompt: event.target.value })} />
        </label>
        <div className="row" style={{ marginTop: 12 }}>
          {TONES.map((tone) => (
            <button key={tone} type="button" className={tone === state.tone ? 'tone on' : 'tone'} onClick={() => patch({ tone })}>{tone}</button>
          ))}
          <select value={state.audience} onChange={(event) => patch({ audience: event.target.value })} style={{ width: 'auto' }}>
            {[...new Set([state.audience, ...AUDIENCES])].map((item) => <option key={item}>{item}</option>)}
          </select>
          <button className="btn primary" type="button" disabled={Boolean(state.busy)} onClick={generate}>產生 3 個方向</button>
        </div>
        <Candidates />
        <Busy />
        <div className="row" style={{ marginTop: 12 }}>
          <label className="field" style={{ width: 96 }}>
            系列則數
            <input
              type="number"
              min="2"
              max="3"
              value={count}
              onChange={(event) => setCount(Math.max(2, Math.min(3, Number(event.target.value) || 2)))}
            />
          </label>
          <button className="btn soft" type="button" disabled={Boolean(state.busy)} onClick={() => runBatch(count)}>一次生成系列</button>
        </div>
        {series.length > 0 ? (
          <div className="series">
            <p className="meta">每個方向各一則。點一則，右邊預覽會換成那一則。</p>
            {series.map((item) => (
              <button
                key={item.id}
                type="button"
                className={state.activeId === item.id ? 'series-card on' : 'series-card'}
                onClick={() => openSeries(item)}
              >
                <b>{item.title}</b>
                <span>{item.status === '草稿' ? item.content.split('\n')[0] : item.status}</span>
              </button>
            ))}
          </div>
        ) : null}
        {active?.status === '生成失敗' ? <p className="notice bad" style={{ marginTop: 12 }}>生成失敗：{active.error}</p> : null}
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn" type="button" onClick={startFresh}>另開一篇</button>
          <button className="btn primary" type="button" disabled={active?.status !== '草稿'} onClick={() => goStage('edit')}>下一步，去編輯</button>
        </div>
      </article>
      <section className="stack">
        {active && active.status !== '生成中' ? (
          <>
            <Canvas compact />
            <p className="meta">這是目前這則的大概樣子。位置和字級要到編輯階段才能調。</p>
            <Preview />
          </>
        ) : (
          <article className="card preview-empty">
            <h3>{active?.status === '生成中' ? 'AI 生成中…' : '預覽會出現在這裡'}</h3>
            <p className="sub">{active?.status === '生成中' ? 'AI 正在寫文案和畫圖卡，完成後會自動跳到編輯。' : '挑一個方向之後，這裡會顯示圖卡和各平台的文字。'}</p>
          </article>
        )}
        <article className="card">
          <h3>參考來源</h3>
          <p className="sub">示範摘要（趨勢情報中心尚未串接新聞來源）。</p>
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
  const { state, patch, rewrite, saveDraft, submitReview, goStage, moveLayout, remember, applyLocal, togglePlatform } = useStudio()
  const [localOpen, setLocalOpen] = useState(false)
  const [localPrompt, setLocalPrompt] = useState('把標題改成更有提問感，並把主色稍微調亮。')
  const length = [...state.content].length
  const busy = Boolean(state.busy)

  return (
    <>
      <div className="grid-2">
        <section className="stack">
          <article className="card">
            <h3>文案</h3>
            <p className="sub">AI 已分別寫好 Threads 與 Instagram 版本。送交之後就不能再改，要等退回。</p>
            <label className="field">
              圖卡標題
              <textarea value={state.title} onChange={(event) => patch({ title: event.target.value })} style={{ minHeight: 64 }} />
            </label>
            <label className="field" style={{ marginTop: 10 }}>
              圖卡副標
              <input value={state.subtitle} onChange={(event) => patch({ subtitle: event.target.value })} />
            </label>
            <label className="field" style={{ marginTop: 10 }}>
              Threads 文案 <span className={length > THREADS_LIMIT ? 'count bad' : 'count'}>{length} / {THREADS_LIMIT}</span>
              <textarea value={state.content} onChange={(event) => patch({ content: event.target.value })} style={{ minHeight: 140 }} />
            </label>
            <label className="field" style={{ marginTop: 10 }}>
              Instagram 文案
              <textarea value={state.igCaption} onChange={(event) => patch({ igCaption: event.target.value })} style={{ minHeight: 120 }} />
            </label>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" type="button" disabled={busy} onClick={() => rewrite('short')}>改短一點</button>
              <button className="btn" type="button" disabled={busy} onClick={() => rewrite('friendly')}>語氣再輕一點</button>
              <button className="btn" type="button" disabled={busy} onClick={() => rewrite('new')}>換一個版本</button>
            </div>
            <p className="meta" style={{ marginTop: 6 }}>這三個按鈕會請 AI 重新生成文案和圖卡（未存的修改會先存起來）。</p>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="meta">這版感覺如何</span>
              {['喜歡', '普通', '不喜歡'].map((rating) => (
                <button key={rating} className="btn" type="button" onClick={() => remember(rating)}>{rating}</button>
              ))}
            </div>
          </article>
          <article className="card">
            <h3>版面</h3>
            <p className="sub">換色、調字，或把文字拖到圖片的空白處。發布時會照這個畫面匯出成圖片。</p>
            <div className="row" style={{ marginBottom: 12 }}>
              <button className="btn" type="button" onClick={() => moveLayout(layoutPreset('top'))}>文字在下</button>
              <button className="btn" type="button" onClick={() => moveLayout(layoutPreset('bottom'))}>文字在上</button>
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
              {state.templates.length ? (
                <div className="swatches" aria-label="圖片模板">
                  <button type="button" className={state.templateId ? 'template-chip none' : 'template-chip none on'} title="不用模板" onClick={() => patch({ templateId: null })}>無</button>
                  {state.templates.map((tpl) => (
                    <button
                      key={tpl.id}
                      type="button"
                      className={tpl.id === state.templateId ? 'template-chip on' : 'template-chip'}
                      style={{ backgroundImage: `url("${tpl.url}")` }}
                      title={tpl.name}
                      onClick={() => patch({ templateId: tpl.id })}
                    />
                  ))}
                </div>
              ) : null}
              <label className="row" style={{ color: '#667085', fontSize: 12.5 }}>
                標題字級
                <input type="range" min="24" max="44" value={state.font} onChange={(event) => patch({ font: Number(event.target.value) })} />
              </label>
              <button className="btn soft" type="button" onClick={() => setLocalOpen(true)}>局部調整</button>
            </div>
          </article>
          <article className="card">
            <h3>發布到哪裡</h3>
            <p className="sub">送審時一起決定。Threads、Instagram 會真的發布；X、Telegram 只是示範。</p>
            <div className="checks">
              {PLATFORMS.map((name) => (
                <label className="check" key={name}>
                  <input type="checkbox" checked={state.platforms.includes(name)} onChange={() => togglePlatform(name)} />
                  {name}{isRealPlatform(name) ? '' : '（示範）'}
                </label>
              ))}
            </div>
          </article>
          <Busy />
          <div className="row">
            <button className="btn" type="button" onClick={() => goStage('write')}>回到撰寫</button>
            <button className="btn" type="button" disabled={busy} onClick={saveDraft}>存成草稿</button>
            <button className="btn primary" type="button" disabled={busy} onClick={submitReview}>送交審核</button>
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
          desc="描述想改的地方。目前認得標題（改成問句）、顏色和字級。"
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
  const item = activeDraft(state)

  return (
    <div className="grid-2">
      <section className="stack">
        <article className="card">
          <h3>確認這則內容</h3>
          <p className="sub">這是唯一的核准。通過之後才能發布；要改字請退回草稿。</p>
          <div className="caption">{state.title}</div>
          <p className="meta" style={{ marginTop: 10 }}>Threads 文案</p>
          <div className="caption">{state.content}</div>
          <p className="meta" style={{ marginTop: 10 }}>Instagram 文案</p>
          <div className="caption">{state.igCaption}</div>
          <p className="meta" style={{ marginTop: 10 }}>發布到：{item?.destinations?.join('、') || '—'}</p>
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

function Results({ item }) {
  if (!item?.publications?.length) return null
  return (
    <div className="list" style={{ marginTop: 12 }}>
      {item.publications.map((pub) => (
        <div className="item result" key={pub.platform}>
          <div>
            <b>{PLATFORM_NAME[pub.platform] || pub.platform}</b>
            <div className="meta">{pub.status === 'failed' ? pub.error_message : pub.status === 'success' ? '已發布' : '處理中…'}</div>
          </div>
          {pub.permalink ? <a className="btn soft" href={pub.permalink} target="_blank" rel="noreferrer">查看貼文</a> : (
            <span className={pub.status === 'failed' ? 'tag red' : 'tag amber'}>{pub.status === 'failed' ? '失敗' : '等待中'}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function PublishStage() {
  const { state, publish, cancelSchedule, returnToDraft, retry, reopen } = useStudio()
  const [when, setWhen] = useState(defaultScheduleInput)
  const item = activeDraft(state)
  const status = item?.status
  const busy = Boolean(state.busy)

  return (
    <div className="grid-2">
      <section className="stack">
        <article className="card">
          <h3>發布</h3>
          {status === '已發布' ? <p className="sub">這則已經發布，只留紀錄，不能再改也不能刪。</p> : null}
          {status === '已排程' ? <p className="sub">已排在 {item.when}。時間到後端會自動發布；取消後回到已核准。</p> : null}
          {status === '已核准' ? <p className="sub">審核已通過。可以直接發，或排一個以後的時間。</p> : null}
          {status === '發布中' ? <p className="sub">正在送到平台…</p> : null}
          {status === '部分發布' ? <p className="sub">有平台失敗。重試只會補發失敗的平台。</p> : null}
          {status === '發布失敗' ? <p className="sub">全部失敗。可以重試，或回到草稿修改後重新送審。</p> : null}
          <p className="meta">目的地：{item?.destinations?.join('、') || '—'}（送審時決定，要改請退回修改）</p>
          {status === '已核准' ? (
            <>
              <label className="field" style={{ marginTop: 14 }}>
                排程時間
                <input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
              </label>
              <div className="row" style={{ marginTop: 14 }}>
                <button className="btn" type="button" onClick={() => returnToDraft(item.id)}>退回修改</button>
                <button className="btn" type="button" disabled={busy} onClick={() => publish(item.id, when)}>排程發布</button>
                <button className="btn primary" type="button" disabled={busy} onClick={() => publish(item.id, '現在')}>直接發布</button>
              </div>
            </>
          ) : null}
          {status === '已排程' ? (
            <div className="row" style={{ marginTop: 14 }}>
              <button className="btn" type="button" onClick={() => cancelSchedule(item.id)}>取消排程</button>
            </div>
          ) : null}
          {status === '部分發布' || status === '發布失敗' ? (
            <div className="row" style={{ marginTop: 14 }}>
              {status === '發布失敗' ? <button className="btn" type="button" onClick={() => reopen(item.id)}>回到草稿</button> : null}
              <button className="btn primary" type="button" disabled={busy} onClick={() => retry(item.id)}>重試發布</button>
            </div>
          ) : null}
          <Busy />
          <Results item={item} />
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
