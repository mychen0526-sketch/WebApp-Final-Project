import { useState } from 'react'
import { AdjustChat } from '../components/AdjustChat.jsx'
import { DragCanvas } from '../components/DragCanvas.jsx'
import { useStudio } from '../context.js'
import { defaultScheduleInput, isRealPlatform, PLATFORM_NAME, REAL_PLATFORM_LIST } from '../lib/posts.js'
import { NewsCard } from './Discover.jsx'
import {
  activeDraft,
  AUDIENCES,
  cardBackground,
  cardCredit,
  LANGUAGES,
  layoutPreset,
  PLATFORM_HINT,
  PLATFORMS,
  platformCaption,
  safetyScan,
  STAGES,
  stageEnabled,
  STYLES,
  TONES,
} from '../studio.js'

const THREADS_LIMIT = 500
const LINKEDIN_LIMIT = 3000
const IMAGE_MODES = [
  ['photo', '用新聞原圖', '照片直接當底圖，圖卡標註出處'],
  ['blend', 'AI 融合', '保留照片構圖，重繪成品牌配色與風格'],
  ['ai', '不用這張圖', '只參考內容，底圖由 AI 產生'],
]
const BUSY_TEXT = {
  candidates: 'AI 正在想 3 個方向…',
  generating: 'AI 正在寫文案、產生圖卡（約 20–60 秒）…',
  series: '正在生成系列…',
  saving: '儲存中…',
  submitting: '匯出圖卡並送審中…',
  publishing: '發布中…',
}

const GEN_STEPS = [
  ['copy', '寫文案'],
  ['card', '圖卡文字'],
  ['image', '產生底圖'],
  ['save', '完成'],
]
const STOPPABLE = new Set(['candidates', 'generating'])
const MODE_LABEL = { short: '改短', friendly: '語氣放輕', new: '換版本' }

// Generation in progress: which step, the Threads copy as it is written, and 「停止」.
function GenerationProgress() {
  const { state, stop } = useStudio()
  const progress = state.progress
  const at = GEN_STEPS.findIndex(([id]) => id === progress?.stage)
  return (
    <div className="gen-progress" aria-live="polite">
      <ol className="gen-steps">
        {GEN_STEPS.map(([id, label], index) => (
          <li key={id} className={index < at ? 'done' : index === at ? 'on' : ''}>{label}</li>
        ))}
      </ol>
      <div className="caption stream-text">
        {progress?.threads || <span className="meta">AI 正在構思…</span>}
        {!progress || progress.stage === 'copy' ? <span className="caret" aria-hidden="true" /> : null}
      </div>
      <div className="row">
        <span className="spinner" />
        <span className="meta grow">{progress?.stage === 'image' ? (state.reference && state.imageMode !== 'ai' ? '處理新聞圖片中…' : '底圖約需 10–40 秒') : '文案寫好後會產生圖卡'}</span>
        <button className="btn" type="button" onClick={stop}>停止</button>
      </div>
    </div>
  )
}

function Busy({ full = false }) {
  const { state, stop } = useStudio()
  if (!state.busy) return null
  if (full && state.busy === 'generating') return <GenerationProgress />
  return (
    <div className="notice busy" style={{ marginTop: 12 }} aria-live="polite">
      <span className="spinner" />
      <span className="grow">{BUSY_TEXT[state.busy] || '處理中…'}</span>
      {STOPPABLE.has(state.busy) ? <button className="link" type="button" onClick={stop}>停止</button> : null}
    </div>
  )
}

// 「‹ 2 / 3 ›」: switch between the AI versions of this post.
function VersionNav() {
  const { state, showVersion } = useStudio()
  const versions = activeDraft(state)?.post?.versions || []
  if (versions.length < 2) return null
  const found = versions.findIndex((item) => item.id === state.versionId)
  const index = found < 0 ? versions.length - 1 : found
  const version = versions[index]
  const edited = version.caption_threads !== state.content || version.caption_instagram !== state.igCaption
  const busy = Boolean(state.busy)
  const go = (next) => {
    if (edited && !window.confirm('目前的修改會被這個版本取代，確定切換？')) return
    showVersion(next)
  }
  return (
    <div className="version-nav" aria-label="AI 版本">
      <button type="button" disabled={busy || index === 0} onClick={() => go(index - 1)} aria-label="上一版">‹</button>
      <span>{index + 1} / {versions.length}</span>
      <button type="button" disabled={busy || index === versions.length - 1} onClick={() => go(index + 1)} aria-label="下一版">›</button>
      <span className="meta">{MODE_LABEL[version.mode] || '初稿'}{edited ? ' · 已修改' : ''}</span>
    </div>
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
          {index + 1} {label}
        </button>
      ))}
      {state.activeId ? (
        <button type="button" className="new-post" disabled={Boolean(state.busy)} onClick={startFresh}>＋ 寫新的一篇</button>
      ) : null}
    </div>
  )
}

// The article this post is based on, and how its picture is used (write + edit stages).
function ReferencePanel({ editing = false }) {
  const { state, searchNews, attachReference, setImageMode, clearReference } = useStudio()
  const [query, setQuery] = useState('')
  const ref = state.reference
  const locked = Boolean(state.busy)

  if (ref) {
    return (
      <div className="reference-panel">
        <div className="reference-head">
          {ref.image_url ? <img src={ref.image_url} alt="" referrerPolicy="no-referrer" /> : null}
          <div className="grow">
            <b>{ref.title}</b>
            <div className="meta">
              {[ref.source, ref.published].filter(Boolean).join(' · ')}
              {' · '}<a href={ref.url} target="_blank" rel="noreferrer">原文</a>
            </div>
          </div>
          <button className="link" type="button" disabled={locked} onClick={clearReference}>移除</button>
        </div>
        {ref.image_url ? (
          <div className="mode-row" role="radiogroup" aria-label="新聞圖片的用法">
            {IMAGE_MODES.map(([id, label, hint]) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={state.imageMode === id}
                className={state.imageMode === id ? 'mode on' : 'mode'}
                disabled={locked}
                title={hint}
                onClick={() => setImageMode(id)}
              >
                {label}
              </button>
            ))}
          </div>
        ) : <p className="meta">這則新聞沒有圖片，只會參考內容。</p>}
        {state.templateId ? <p className="meta">目前套用了圖片模板，模板會優先當底圖。</p> : null}
        {editing ? <p className="meta">圖片用法改了之後，按「換一個版本」重新產生圖卡。</p> : null}
      </div>
    )
  }

  const results = state.research.results.slice(0, 4)
  const submit = (event) => {
    event.preventDefault()
    searchNews(query || state.prompt.slice(0, 40))
  }
  return (
    <div className="reference-panel">
      <form className="row search-row" onSubmit={submit}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋相關新聞與圖片（空白則用主題）" aria-label="搜尋新聞" />
        <button className="btn" type="submit" disabled={state.research.loading || locked}>{state.research.loading ? '搜尋中…' : '搜尋'}</button>
      </form>
      {results.length ? (
        <div className="news-grid compact">
          {results.map((item) => (
            <NewsCard key={item.url} item={item} compact onUse={attachReference} onOpen={() => window.open(item.url, '_blank', 'noreferrer')} />
          ))}
        </div>
      ) : <p className="meta">加上一則真實新聞，AI 會引用它的內容，圖卡也能用它的照片。</p>}
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
      credit={cardCredit(state)}
      onLayout={draggable ? moveLayout : undefined}
    />
  )
}

function Preview({ platforms = PLATFORMS }) {
  const { state, patch } = useStudio()
  const current = platforms.includes(state.platform) ? state.platform : platforms[0]
  return (
    <div className="preview-pane">
      <div className="tabs">
        {platforms.map((name) => (
          <button
            key={name}
            type="button"
            className={current === name ? 'on' : ''}
            onClick={() => patch({ platform: name })}
          >
            {name}{isRealPlatform(name) ? '' : ' · 示範'}
          </button>
        ))}
      </div>
      <div className="caption">{platformCaption(state, current) || '還沒有內文'}</div>
      <p className="meta" style={{ marginTop: 8 }}>{PLATFORM_HINT[current]}</p>
    </div>
  )
}

function WriteStage() {
  const { state, patch, generate, runBatch, openSeries, goStage, startFresh, pickCandidate } = useStudio()
  const [count, setCount] = useState(3)
  const [showMore, setShowMore] = useState(false)
  const series = state.series.map((id) => state.drafts.find((item) => item.id === id)).filter(Boolean)
  const active = activeDraft(state)
  const picking = state.candidates.length > 0 && !active

  if (picking) {
    return (
      <section className="write-focus">
        <div className="write-head">
          <h3>挑一個方向</h3>
          <p className="sub">選一則後會開始寫文案與圖卡。</p>
        </div>
        <div className="candidate-grid">
          {state.candidates.map((item) => (
            <button key={item.title} type="button" className="candidate" disabled={Boolean(state.busy)} onClick={() => pickCandidate(item)}>
              <b>{item.title}</b>
              <span>{item.angle}</span>
              <span>開頭：{item.hook}</span>
            </button>
          ))}
        </div>
        <Busy />
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn" type="button" disabled={Boolean(state.busy)} onClick={() => patch({ candidates: [] })}>回到輸入</button>
          <button className="btn soft" type="button" disabled={Boolean(state.busy)} onClick={generate}>再給一組方向</button>
        </div>
      </section>
    )
  }

  return (
    <div className="grid-write">
      <article className="surface write-main">
        <h3>這篇要講什麼</h3>
        <p className="sub">寫下主題，產生三個方向後再挑一個。</p>
        <label className="field">
          主題或貼文方向
          <textarea
            className="prompt-area"
            value={state.prompt}
            onChange={(event) => patch({ prompt: event.target.value })}
            placeholder="例如：整理近期 AI 產品商業化趨勢，給創業者看"
          />
        </label>
        <div className="row" style={{ marginTop: 12 }}>
          {TONES.map((tone) => (
            <button key={tone} type="button" className={tone === state.tone ? 'tone on' : 'tone'} onClick={() => patch({ tone })}>{tone}</button>
          ))}
          <select value={state.audience} onChange={(event) => patch({ audience: event.target.value })} style={{ width: 'auto' }}>
            {[...new Set([state.audience, ...AUDIENCES])].map((item) => <option key={item}>{item}</option>)}
          </select>
          <select
            value={state.language || 'zh'}
            onChange={(event) => patch({ language: event.target.value })}
            style={{ width: 'auto' }}
            aria-label="文案語言"
            title={LANGUAGES.find(([id]) => id === (state.language || 'zh'))?.[2]}
          >
            {LANGUAGES.map(([id, label]) => <option key={id} value={id}>文案：{label}</option>)}
          </select>
        </div>
        <div style={{ marginTop: 14 }}>
          <span className="field-label">參考新聞與圖片 <span className="meta">（選填）</span></span>
          <ReferencePanel />
        </div>
        {state.busy !== 'generating' ? <Busy /> : null}
        {active?.status === '生成失敗' ? <p className="notice bad" style={{ marginTop: 12 }}>生成失敗：{active.error}</p> : null}
        <div className="action-bar">
          <button className="btn" type="button" onClick={startFresh}>清空重來</button>
          {active?.status === '草稿' ? (
            <button className="btn primary" type="button" onClick={() => goStage('edit')}>下一步，去編輯</button>
          ) : (
            <button className="btn primary" type="button" disabled={Boolean(state.busy) || !state.prompt.trim()} onClick={generate}>
              產生 3 個方向
            </button>
          )}
        </div>
        <button type="button" className="link more-toggle" onClick={() => setShowMore((value) => !value)}>
          {showMore ? '收起進階選項' : '進階：一次生成系列'}
        </button>
        {showMore ? (
          <div className="more-panel">
            <p className="meta">會依 3 個方向各生成一則草稿，仍可在內容庫裡分開編輯。</p>
            <div className="row" style={{ marginTop: 8 }}>
              <label className="field" style={{ width: 96 }}>
                則數
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
              <div className="series" style={{ marginTop: 12 }}>
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
          </div>
        ) : null}
      </article>
      <section className="stack">
        {active && active.status !== '生成中' ? (
          <>
            <Canvas compact />
            <p className="meta">圖卡預覽</p>
            <Preview platforms={REAL_PLATFORM_LIST} />
          </>
        ) : (
          <article className="preview-empty">
            <h3>{active?.status === '生成中' ? '生成中' : '圖卡預覽'}</h3>
            <p className="sub">
              {active?.status === '生成中' ? '完成後會進編輯。' : '選好方向後會出現在這裡。'}
            </p>
            <Busy full />
          </article>
        )}
      </section>
    </div>
  )
}

function EditStage() {
  const { state, patch, rewrite, saveDraft, submitReview, goStage, moveLayout, remember, togglePlatform } = useStudio()
  const [copyTab, setCopyTab] = useState('Threads')
  const [layoutOpen, setLayoutOpen] = useState(false)
  const length = [...state.content].length
  const linkedinLength = [...(state.linkedinCaption || '')].length
  const busy = Boolean(state.busy)

  return (
    <>
      <div className="grid-edit">
        <section className="stack edit-tools">
          <article className="surface">
            <h3>文案</h3>
            <p className="sub">先改字；圖卡在右側。送審後需退回才能再改。</p>
            <label className="field">
              圖卡標題
              <textarea value={state.title} onChange={(event) => patch({ title: event.target.value })} style={{ minHeight: 56 }} />
            </label>
            <label className="field" style={{ marginTop: 10 }}>
              圖卡副標
              <input value={state.subtitle} onChange={(event) => patch({ subtitle: event.target.value })} />
            </label>
            <div className="tabs" style={{ marginTop: 14 }}>
              {REAL_PLATFORM_LIST.map((name) => (
                <button key={name} type="button" className={copyTab === name ? 'on' : ''} onClick={() => setCopyTab(name)}>{name}</button>
              ))}
            </div>
            {copyTab === 'Threads' ? (
              <label className="field">
                Threads 文案 <span className={length > THREADS_LIMIT ? 'count bad' : 'count'}>{length} / {THREADS_LIMIT}</span>
                <textarea value={state.content} onChange={(event) => patch({ content: event.target.value })} style={{ minHeight: 160 }} />
              </label>
            ) : null}
            {copyTab === 'Instagram' ? (
              <label className="field">
                Instagram 文案
                <textarea value={state.igCaption} onChange={(event) => patch({ igCaption: event.target.value })} style={{ minHeight: 160 }} />
              </label>
            ) : null}
            {copyTab === 'LinkedIn' ? (
              <label className="field">
                LinkedIn 文案 <span className={linkedinLength > LINKEDIN_LIMIT ? 'count bad' : 'count'}>{linkedinLength} / {LINKEDIN_LIMIT}</span>
                <textarea value={state.linkedinCaption} onChange={(event) => patch({ linkedinCaption: event.target.value })} style={{ minHeight: 220 }} />
              </label>
            ) : null}
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" type="button" disabled={busy} onClick={() => rewrite('short')}>改短一點</button>
              <button className="btn" type="button" disabled={busy} onClick={() => rewrite('friendly')}>語氣再輕一點</button>
              <button className="btn" type="button" disabled={busy} onClick={() => rewrite('new')}>換一個版本</button>
              <VersionNav />
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="meta">這版感覺如何</span>
              {['喜歡', '普通', '不喜歡'].map((rating) => (
                <button key={rating} className="btn" type="button" onClick={() => remember(rating)}>{rating}</button>
              ))}
            </div>
          </article>

          <article className="surface">
            <button type="button" className="panel-toggle" onClick={() => setLayoutOpen((value) => !value)}>
              <span>
                <b>版面與模板</b>
                <span className="meta">配色、字級、模板</span>
              </span>
              <span aria-hidden="true">{layoutOpen ? '▾' : '▸'}</span>
            </button>
            {layoutOpen ? (
              <div className="panel-body">
                <div style={{ marginBottom: 14 }}>
                  <span className="field-label">新聞圖片</span>
                  <ReferencePanel editing />
                </div>
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
                </div>
              </div>
            ) : null}
          </article>

          <article className="surface">
            <h3>發布到哪裡</h3>
            <p className="sub">Threads、Instagram、LinkedIn 正式發布；其餘為示範。</p>
            <div className="checks">
              {PLATFORMS.map((name) => (
                <label className="check" key={name}>
                  <input type="checkbox" checked={state.platforms.includes(name)} onChange={() => togglePlatform(name)} />
                  {name}{isRealPlatform(name) ? '' : '（示範）'}
                </label>
              ))}
            </div>
          </article>

          <Busy full />
          <div className="action-bar">
            <button className="btn" type="button" onClick={() => goStage('write')}>上一步</button>
            <button className="btn" type="button" disabled={busy} onClick={saveDraft}>存成草稿</button>
            <button className="btn primary" type="button" disabled={busy} onClick={submitReview}>送交審核</button>
          </div>
        </section>

        <section className="stack edit-canvas">
          <p className="meta canvas-hint">拖曳文字調整位置</p>
          {state.imageNote ? <p className="notice">{state.imageNote}</p> : null}
          <Canvas draggable />
          <AdjustChat key={state.activeId} />
          <Preview />
        </section>
      </div>
    </>
  )
}

function ReviewStage() {
  const { state, approve, returnToDraft } = useStudio()
  const scan = safetyScan(state)
  const [checked, setChecked] = useState({ read: false, rights: false })
  const [tab, setTab] = useState('Threads')
  const item = activeDraft(state)

  return (
    <div className="grid-edit">
      <section className="stack edit-tools">
        <article className="surface">
          <h3>確認這則內容</h3>
          <p className="sub">核准一次即可。要改字請退回。</p>
          <div className="caption tight"><b>{state.title}</b>{state.subtitle ? `\n${state.subtitle}` : ''}</div>
          <div className="tabs" style={{ marginTop: 12 }}>
            {REAL_PLATFORM_LIST.map((name) => (
              <button key={name} type="button" className={tab === name ? 'on' : ''} onClick={() => setTab(name)}>{name}</button>
            ))}
          </div>
          <div className="caption">{platformCaption(state, tab)}</div>
          <p className="meta" style={{ marginTop: 10 }}>發布到：{item?.destinations?.join('、') || '—'}</p>
          <div className={scan.detected.length ? 'notice bad' : 'notice'} style={{ marginTop: 12 }}>{scan.risks}</div>
          {cardCredit(state) ? (
            <div className="notice" style={{ marginTop: 8 }}>
              圖卡使用了新聞圖片（{cardCredit(state).replace('圖片來源：', '')}）。請確認你有權使用，或退回改用「AI 融合」／AI 底圖。
            </div>
          ) : null}
          <label className="check" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={checked.read} onChange={(event) => setChecked((value) => ({ ...value, read: event.target.checked }))} />
            我已讀過全文，確認可以對外發布
          </label>
          <label className="check" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={checked.rights} onChange={(event) => setChecked((value) => ({ ...value, rights: event.target.checked }))} />
            圖片與文字都有使用權利
          </label>
          <div className="action-bar">
            <button className="btn" type="button" onClick={() => returnToDraft(state.activeId)}>退回修改</button>
            <button className="btn primary" type="button" disabled={!(checked.read && checked.rights)} onClick={approve}>核准</button>
          </div>
        </article>
      </section>
      <section className="stack edit-canvas">
        <Canvas />
        <Preview platforms={REAL_PLATFORM_LIST} />
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
    <div className="grid-edit">
      <section className="stack edit-tools">
        <article className="surface">
          <h3>發布</h3>
          {status === '已發布' ? <p className="sub">這則已經發布，只留紀錄。</p> : null}
          {status === '已排程' ? <p className="sub">已排在 {item.when}。取消後會回到已核准。</p> : null}
          {status === '已核准' ? <p className="sub">審核已通過。選一個主動作即可。</p> : null}
          {status === '發布中' ? <p className="sub">正在送到平台…</p> : null}
          {status === '部分發布' ? <p className="sub">有平台失敗。重試只會補發失敗的平台。</p> : null}
          {status === '發布失敗' ? <p className="sub">全部失敗。可以重試，或回到草稿修改。</p> : null}
          <p className="meta">目的地：{item?.destinations?.join('、') || '—'}</p>
          {status === '已核准' ? (
            <>
              <label className="field" style={{ marginTop: 14 }}>
                排程時間
                <input type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
              </label>
              <div className="action-bar">
                <button className="btn" type="button" onClick={() => returnToDraft(item.id)}>退回修改</button>
                <button className="btn" type="button" disabled={busy} onClick={() => publish(item.id, when)}>排程</button>
                <button className="btn primary" type="button" disabled={busy} onClick={() => publish(item.id, '現在')}>現在發布</button>
              </div>
            </>
          ) : null}
          {status === '已排程' ? (
            <div className="action-bar">
              <button className="btn" type="button" onClick={() => cancelSchedule(item.id)}>取消排程</button>
            </div>
          ) : null}
          {status === '部分發布' || status === '發布失敗' ? (
            <div className="action-bar">
              {status === '發布失敗' ? <button className="btn" type="button" onClick={() => reopen(item.id)}>回到草稿</button> : null}
              <button className="btn primary" type="button" disabled={busy} onClick={() => retry(item.id)}>重試發布</button>
            </div>
          ) : null}
          <Busy />
          <Results item={item} />
        </article>
      </section>
      <section className="stack edit-canvas">
        <Canvas />
        <Preview platforms={REAL_PLATFORM_LIST} />
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
