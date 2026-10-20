import { useMemo, useState } from 'react'
import { Shell, Top } from './components/ui.jsx'
import { StudioContext } from './context.js'
import { CalendarPage } from './pages/Calendar.jsx'
import { DiscoverPage } from './pages/Discover.jsx'
import { LibraryPage } from './pages/Library.jsx'
import { ReviewPage } from './pages/Review.jsx'
import { SettingsPage } from './pages/Settings.jsx'
import { TemplatesPage } from './pages/Templates.jsx'
import { WorkspacePage } from './pages/Workspace.jsx'
import { activeDraft, initialState, layoutPreset, pageTitle, scanText, STAGES, stageEnabled, STYLES } from './studio.js'

const PAGES = {
  workspace: WorkspacePage,
  discover: DiscoverPage,
  library: LibraryPage,
  calendar: CalendarPage,
  review: ReviewPage,
  templates: TemplatesPage,
  settings: SettingsPage,
}

export default function App() {
  const [state, setState] = useState(initialState)
  const [toast, setToast] = useState(null)

  const api = useMemo(() => {
    const notify = (title, text) => {
      setToast({ title, text })
      window.setTimeout(() => setToast((current) => (current?.title === title ? null : current)), 2800)
    }

    const patch = (partial) => {
      setState((current) => ({ ...current, ...partial }))
    }

    const statusOf = (id = state.activeId) => state.drafts.find((item) => item.id === id)?.status

    const canEdit = () => {
      const status = statusOf()
      if (status && status !== '草稿') {
        notify('這則不能再修改', '待審核和已核准要先退回成草稿。')
        return false
      }
      if (state.stage !== 'write' && state.stage !== 'edit') {
        notify('這個階段不能改內容', '請回到撰寫或編輯。')
        return false
      }
      return true
    }

    const workingDraft = (status, extra = {}) => {
      const id = state.activeId ?? Date.now()
      const next = {
        id,
        title: state.title.replaceAll('\n', ' '),
        content: state.content,
        status,
        date: '10/20',
        layout: state.layout,
        style: state.style,
        font: state.font,
        ...extra,
      }
      const drafts = state.drafts.some((item) => item.id === id)
        ? state.drafts.map((item) => (item.id === id ? { ...item, ...next } : item))
        : [next, ...state.drafts]
      return { drafts, activeId: id }
    }

    const loadItem = (item, stage) => ({
      page: 'workspace',
      stage,
      activeId: item.id,
      title: item.title,
      content: item.content,
      layout: item.layout || state.layout,
      style: item.style ?? state.style,
      font: item.font ?? state.font,
      themeName: STYLES[item.style ?? state.style][2],
    })

    return {
      state,
      notify,
      patch,
      navigate: (page) => patch({ page }),
      goStage(stage) {
        if (stage === 'edit' && !state.content.trim()) {
          notify('還沒有內容', '先生成初稿，或寫一點內文。')
          return
        }
        if (!stageEnabled(state, stage)) {
          notify('這個階段還沒到', '送交之後才能審核，核准之後才能發布。')
          return
        }
        patch({ stage, page: 'workspace' })
      },
      startFresh() {
        patch({
          page: 'workspace',
          stage: 'write',
          activeId: null,
          series: [],
          title: '',
          content: '',
        })
      },
      generate() {
        if (!canEdit()) return
        const title = state.tone === '輕鬆分享' ? '今天用三分鐘\n看懂 AI 商業化' : 'AI 如何改變\n產品上市速度？'
        const content = `${state.tone}｜${state.audience}\n\n${state.prompt}\n\n根據最近的科技趨勢，AI 正從單點工具變成可嵌入產品流程的能力。對新創而言，重點不是追逐所有新模型，而是找到能縮短驗證週期、改善交付品質的應用場景。\n\n#人工智慧 #科技趨勢 #產品開發`
        patch({ content, title, series: [], activeId: null, stage: 'write' })
        notify('已產生初稿', '到編輯階段可以改字和排版。要留下再存成草稿。')
      },
      rewrite(mode) {
        if (!canEdit()) return
        let content = state.content
        if (mode === 'short') content = state.content.split('\n').filter(Boolean).slice(0, 2).join('\n\n')
        if (mode === 'friendly') content = state.content.replace('真正的競爭力', '我覺得真正有趣的地方').replace('創業團隊', '大家')
        if (mode === 'new') content = `另一個版本：\n\n${state.prompt}\n\n若以${state.audience}為對象，可以用「問題—觀察—行動建議」的方式重寫這篇貼文。`
        patch({ content })
        notify('已重寫', '沿用目前主題，產出另一個示範版本。')
      },
      applyLocal(prompt) {
        if (!canEdit()) return
        let style = state.style
        let title = state.title
        let font = state.font
        if (prompt.includes('標題')) title = '如果 AI 能把上市\n時間縮短一半？'
        if (prompt.includes('亮') || prompt.includes('色')) style = (style + 1) % STYLES.length
        if (prompt.includes('字')) font = Math.min(46, font + 4)
        patch({ title, style, font, themeName: STYLES[style][2] })
        notify('已套用局部調整', '只改了標題、色彩或字級，正文維持原樣。')
      },
      saveDraft() {
        const current = activeDraft(state)
        if (current && current.status !== '草稿') {
          notify('這則不能存成草稿', '只有還沒送審的內容可以覆蓋儲存。')
          return
        }
        if (!state.content.trim()) {
          notify('還沒有內容', '先寫一點再存。')
          return
        }
        patch(workingDraft('草稿'))
        notify('已存成草稿', '可在內容資料庫繼續編輯。')
      },
      submitReview() {
        const current = activeDraft(state)
        if (current && current.status !== '草稿') {
          notify('已經送出', '這則正在審核，或已經核准。')
          return
        }
        if (!state.content.trim()) {
          notify('還沒有內容', '先寫完再送審。')
          return
        }
        const saved = workingDraft('待審核')
        patch({
          ...saved,
          stage: 'review',
          series: state.series.filter((item) => item.id !== saved.activeId),
        })
        notify('已送交審核', '內容已鎖定。核准或退回都在審核這一步。')
      },
      approve() {
        const item = activeDraft(state)
        if (!item || item.status !== '待審核') {
          notify('沒有待審內容', '請先從編輯階段送交審核。')
          return
        }
        patch({
          drafts: state.drafts.map((draft) => (draft.id === item.id ? { ...draft, status: '已核准' } : draft)),
          stage: 'publish',
        })
        notify('審核通過', '現在可以直接發布或排程。不需要再核准一次。')
      },
      returnToDraft(id) {
        const item = state.drafts.find((draft) => draft.id === id)
        if (!item || (item.status !== '待審核' && item.status !== '已核准')) {
          notify('不能退回', '只有待審核或已核准可以退回成草稿。已排程請先取消排程。')
          return
        }
        patch({
          ...loadItem({ ...item, style: item.style }, 'edit'),
          drafts: state.drafts.map((draft) => (draft.id === id ? { ...draft, status: '草稿', when: null, destinations: null } : draft)),
        })
        notify('已退回草稿', '可以再修改。改完要重新送審。')
      },
      publish(id, when) {
        const item = state.drafts.find((draft) => draft.id === id)
        if (!item || item.status !== '已核准') {
          notify('尚未核准', '只有已核准的內容可以發布。')
          return false
        }
        const scan = scanText(state.sensitive, item.title, item.content)
        if (scan.detected.length) {
          notify('安全檢查未通過', `請先退回修改，再處理敏感詞：${scan.detected.join('、')}`)
          return false
        }
        if (!state.platforms.length) {
          notify('尚未選擇平台', '至少要勾選一個發布目的地。')
          return false
        }
        const now = when === '現在'
        if (!now && new Date(String(when).replace(' ', 'T')).getTime() <= Date.now()) {
          notify('時間已經過了', '排程請選現在之後的時間。')
          return false
        }
        const stamp = now ? '2026-10-20 現在' : String(when).replace('T', ' ')
        patch({
          ...loadItem(item, 'publish'),
          page: now ? state.page : 'calendar',
          drafts: state.drafts.map((draft) => (
            draft.id === id
              ? { ...draft, status: now ? '已發布' : '已排程', when: stamp, destinations: [...state.platforms] }
              : draft
          )),
        })
        notify(now ? '已送出發布' : '已加入排程', `${state.platforms.join('、')} · ${stamp}`)
        return true
      },
      cancelSchedule(id) {
        const item = state.drafts.find((draft) => draft.id === id)
        if (!item || item.status !== '已排程') return
        patch({
          drafts: state.drafts.map((draft) => (
            draft.id === id ? { ...draft, status: '已核准', when: null, destinations: null } : draft
          )),
        })
        notify('已取消排程', '內容回到已核准，日曆上的這筆也一併移除。')
      },
      useSource(source) {
        const locked = activeDraft(state) && activeDraft(state).status !== '草稿'
        patch({
          page: 'workspace',
          stage: 'write',
          activeId: locked ? null : state.activeId,
          series: locked ? [] : state.series,
          prompt: `參考「${source.title}」，為${state.audience}撰寫一篇${state.tone}貼文。重點：${source.summary}`,
        })
        notify('已帶入參考資料', '主題已更新。生成後再到編輯階段。')
      },
      addSource(url) {
        const clean = url.trim()
        if (!clean) return
        patch({
          sources: [{ title: clean.replace(/^https?:\/\//, '').slice(0, 42), type: 'RSS / 網站', origin: '使用者新增的示範來源', date: '2026/10/20', summary: '這是新增來源的示意資料，正式版會在這裡抓標題與摘要。' }, ...state.sources],
        })
        notify('已加入來源', '目前以示範摘要呈現，尚未實際抓取網頁。')
      },
      openItem(item) {
        const stage = {
          草稿: 'edit',
          待審核: 'review',
          已核准: 'publish',
          已排程: 'publish',
          已發布: 'publish',
        }[item.status] || 'edit'
        patch(loadItem(item, stage))
      },
      deleteDraft(id) {
        const item = state.drafts.find((draft) => draft.id === id)
        if (!item || item.status !== '草稿') {
          notify('不能刪除', '已送審、已排程或已發布的內容要留著。排程請改按取消。')
          return
        }
        patch({
          drafts: state.drafts.filter((draft) => draft.id !== id),
          series: state.series.filter((draft) => draft.id !== id),
          activeId: state.activeId === id ? null : state.activeId,
          stage: state.activeId === id ? 'write' : state.stage,
        })
        notify('已刪除草稿', '這則還沒送出，所以可以刪。')
      },
      applyTemplate(index, tone) {
        const locked = activeDraft(state) && activeDraft(state).status !== '草稿'
        patch({
          style: index,
          themeName: STYLES[index][2],
          tone: tone || state.tone,
          page: 'workspace',
          stage: locked ? 'write' : state.stage,
          activeId: locked ? null : state.activeId,
        })
        notify('已套用版型', `${STYLES[index][2]}。鎖定中的內容不會被改到。`)
      },
      runBatch(count) {
        if (!canEdit()) return
        const made = Array.from({ length: count }, (_, index) => ({
          id: Date.now() + index,
          title: `${state.prompt.slice(0, 18)} · ${index + 1}`,
          content: `系列第 ${index + 1} 則，共 ${count} 則。\n\n${state.prompt}\n\n以${state.tone}撰寫，對象是${state.audience}。`,
          status: '草稿',
          date: '10/20',
          layout: layoutPreset(index % 2 === 0 ? 'top' : 'bottom'),
          style: state.style,
          font: state.font,
        }))
        const first = made[0]
        patch({
          drafts: [...made, ...state.drafts],
          series: made,
          title: first.title,
          content: first.content,
          layout: first.layout,
          activeId: first.id,
          stage: 'write',
        })
        notify('系列已放上工作台', '點一則，再按下一步去編輯。')
      },
      openSeries(item) {
        if (item.status && item.status !== '草稿') return
        patch({
          title: item.title,
          content: item.content,
          layout: item.layout || state.layout,
          activeId: item.id,
        })
      },
      moveLayout(layout) {
        if (!canEdit()) return
        patch({
          layout,
          series: state.series.map((item) => (item.id === state.activeId ? { ...item, layout } : item)),
          drafts: state.drafts.map((item) => (item.id === state.activeId && item.status === '草稿' ? { ...item, layout } : item)),
        })
      },
      remember(rating) {
        patch({ feedback: [{ rating, text: state.content.slice(0, 42), time: '剛剛' }, ...state.feedback] })
        notify('已記下這次回饋', '之後會用來調整語氣與版型偏好。')
      },
      addWord(word) {
        const clean = word.trim()
        if (!clean || state.sensitive.includes(clean)) return
        patch({ sensitive: [...state.sensitive, clean] })
      },
      removeWord(word) {
        patch({ sensitive: state.sensitive.filter((item) => item !== word) })
      },
      togglePlatform(name) {
        const platforms = state.platforms.includes(name)
          ? state.platforms.filter((item) => item !== name)
          : [...state.platforms, name]
        patch({ platforms })
      },
    }
  }, [state])

  const Page = PAGES[state.page] || WorkspacePage
  const active = activeDraft(state)

  return (
    <StudioContext.Provider value={api}>
      <Shell state={state} onNavigate={api.navigate}>
        <Top kicker="Orbit Studio" title={pageTitle(state.page)} note="示範資料，不會連到真正的模型或社群平台。">
          {state.page === 'workspace' ? (
            <>
              <span className="chip">{STAGES.find(([id]) => id === state.stage)?.[1] || '撰寫'}</span>
              <span className="chip">{active?.status || '尚未存檔'}</span>
            </>
          ) : (
            <span className="chip">{state.themeName}</span>
          )}
        </Top>
        <Page />
      </Shell>
      {toast ? (
        <div className="toast" role="status">
          <b>{toast.title}</b>
          {toast.text}
        </div>
      ) : null}
    </StudioContext.Provider>
  )
}
