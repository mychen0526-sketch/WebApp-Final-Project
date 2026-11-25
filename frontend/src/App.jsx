import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Shell, Top } from './components/ui.jsx'
import { StudioContext } from './context.js'
import { api, API_BASE, isAbort } from './lib/api.js'
import { AuthError, currentUser, DEV_MODE, signOut } from './lib/auth.js'
import { exportCard } from './lib/exportCard.js'
import { isBusy, layoutName, mergeDraft, patchBody, PLATFORM_NAME, REAL_PLATFORMS, shortDate, toDraft, withLocalOffset } from './lib/posts.js'
import { CalendarPage } from './pages/Calendar.jsx'
import { DiscoverPage } from './pages/Discover.jsx'
import { LibraryPage } from './pages/Library.jsx'
import { LoginPage } from './pages/Login.jsx'
import { ReviewPage } from './pages/Review.jsx'
import { SettingsPage } from './pages/Settings.jsx'
import { TemplatesPage } from './pages/Templates.jsx'
import { WorkspacePage } from './pages/Workspace.jsx'
import { activeDraft, cardBackground, cardCredit, initialState, pageTitle, stageEnabled, STYLES, templateOf } from './studio.js'

const PAGES = {
  workspace: WorkspacePage,
  discover: DiscoverPage,
  library: LibraryPage,
  calendar: CalendarPage,
  review: ReviewPage,
  templates: TemplatesPage,
  settings: SettingsPage,
}

const RATING = { 喜歡: 'like', 普通: 'neutral', 不喜歡: 'dislike' }
const RATING_LABEL = { like: '喜歡', neutral: '普通', dislike: '不喜歡' }
const STAGE_OF = { 草稿: 'edit', 待審核: 'review', 生成中: 'write', 生成失敗: 'write' }
const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

function platformsFromSettings(settings) {
  const ids = settings?.default_platforms || []
  return ids.map((id) => PLATFORM_NAME[id]).filter(Boolean)
}

export default function App() {
  const [user, setUser] = useState(currentUser)
  const logout = useCallback(() => {
    signOut()
    setUser(null)
  }, [])
  if (!user) return <LoginPage onLogin={setUser} />
  return <Studio user={user} onLogout={logout} />
}

function editorFields(item, stage) {
  return {
    page: 'workspace',
    stage,
    activeId: item.id,
    title: item.title,
    subtitle: item.subtitle || '',
    description: item.description || '',
    content: item.content,
    igCaption: item.igCaption,
    linkedinCaption: item.linkedinCaption,
    canvas: item.post?.canvas_json || null,
    background: item.background,
    reference: item.reference,
    imageMode: item.reference ? item.imageMode : undefined,
    credit: item.credit,
    imageNote: item.imageNote,
    layout: item.layout,
    style: item.style,
    font: item.font,
    templateId: item.templateId,
    themeName: STYLES[item.style]?.[2] || STYLES[0][2],
    tone: item.tone || undefined,
    audience: item.audience || undefined,
    language: item.language,
    prompt: item.goal || undefined,
    // Always restore the checklist (including empty → fall back to Threads only when never set).
    platforms: item.destinations?.length ? item.destinations : ['Threads'],
    versionId: item.post?.versions?.at(-1)?.id ?? null,
  }
}

function withoutUndefined(object) {
  return Object.fromEntries(Object.entries(object).filter(([, value]) => value !== undefined))
}

function Studio({ user, onLogout }) {
  const [state, setState] = useState(initialState)
  const [toast, setToast] = useState(null)
  const stateRef = useRef(state)
  stateRef.current = state
  // What「停止」stops: an in-flight request (candidates) or a generating post.
  const abortRef = useRef(null)
  const followRef = useRef({ id: null, cancelled: false })

  const notify = useCallback((title, text, { sticky = false } = {}) => {
    setToast({ title, text, sticky })
    if (sticky) return
    window.setTimeout(() => setToast((current) => (
      current?.title === title && !current.sticky ? null : current
    )), 4200)
  }, [])

  const patch = useCallback((partial) => setState((current) => ({ ...current, ...partial })), [])

  const fail = useCallback((error, title = '操作沒有完成') => {
    if (error instanceof AuthError) {
      onLogout()
      return
    }
    // Errors stay until「知道了」; success toasts still auto-dismiss.
    notify(title, error.message || String(error), { sticky: true })
  }, [notify, onLogout])

  // Put a backend post into the list (and refresh the editor if it is the open one).
  const upsert = useCallback((post, { load } = {}) => {
    setState((current) => {
      const old = current.drafts.find((item) => item.id === post.id)
      const item = mergeDraft(old, post)
      const drafts = old ? current.drafts.map((d) => (d.id === post.id ? item : d)) : [item, ...current.drafts]
      const next = { ...current, drafts }
      if (load) return { ...next, ...withoutUndefined(editorFields(item, load)) }
      return next
    })
    return toDraft(post)
  }, [])

  const refreshPosts = useCallback(async () => {
    try {
      const posts = await api.listPosts()
      setState((current) => ({
        ...current,
        drafts: posts.map((post) => mergeDraft(current.drafts.find((item) => item.id === post.id), post)),
      }))
    } catch (error) {
      fail(error, '讀取貼文失敗')
    }
  }, [fail])

  const refreshAccounts = useCallback(async () => {
    try {
      patch({ accounts: await api.accounts() })
    } catch (error) {
      fail(error, '讀取平台帳號失敗')
    }
  }, [fail, patch])

  // Poll one post until `done(post)` (generation / publishing run in the background on the server).
  const poll = useCallback(async (id, done, { load, limitMs = 5 * 60 * 1000 } = {}) => {
    const started = Date.now()
    while (Date.now() - started < limitMs) {
      await sleep(2000)
      const post = await api.getPost(id)
      const finished = done(post)
      upsert(post, { load: finished && stateRef.current.activeId === id ? load?.(post) : undefined })
      if (finished) return post
    }
    throw new Error('等太久了，請到內容資料庫重新整理看看')
  }, [upsert])

  // Follow a generating post over the SSE stream (copy appears as it is written);
  // fall back to polling when the stream cannot be opened.
  const follow = useCallback(async (id, { load } = {}) => {
    followRef.current = { id, cancelled: false }
    const onProgress = (progress) => setState((current) => ({ ...current, progress }))
    let post
    try {
      post = await api.followPost(id, { onProgress })
    } catch (error) {
      if (error instanceof AuthError) throw error
      post = await poll(id, (item) => item.status !== 'generating')
    } finally {
      patch({ progress: null })
    }
    upsert(post, { load: stateRef.current.activeId === id ? load?.(post) : undefined })
    return post
  }, [patch, poll, upsert])

  // First load: who am I talking to, and everything this user already has.
  useEffect(() => {
    let alive = true
    api.health().then((health) => alive && patch({ health })).catch(() => alive && patch({ health: { error: true } }))
    // Load each part on its own so one failing endpoint does not blank the whole studio.
    const load = (promise, apply, label) => promise
      .then((data) => alive && setState((current) => ({ ...current, ...apply(data, current) })))
      .catch((error) => alive && fail(error, `讀取${label}失敗`))
    load(api.listPosts(), (posts) => ({ drafts: posts.map(toDraft) }), '貼文')
    load(api.getSettings(), (settings, current) => {
      const defaults = platformsFromSettings(settings)
      return {
        tone: settings.default_tone || current.tone,
        audience: settings.default_audience || current.audience,
        sensitive: settings.sensitive_words || current.sensitive,
        company: settings.brand_name || current.company,
        // BUG-13: restore default destinations; do not let accounts() overwrite this later.
        platforms: defaults.length ? defaults : current.platforms,
      }
    }, '偏好設定')
    load(api.accounts(), (accounts) => ({ accounts }), '平台帳號')
    load(api.listFeedback(), (rows) => ({
      feedback: (rows || []).map((row) => ({
        rating: RATING_LABEL[row.rating] || row.rating,
        text: row.post_title || '',
        time: shortDate(row.created_at) || '',
      })),
    }), '回饋')
    load(api.listTemplates(), (templates, current) => {
      const list = templates.map((t) => ({ id: t.id, name: t.name, url: t.public_url }))
      const stillThere = list.some((tpl) => tpl.id === current.templateId)
      return {
        templates: list,
        // BUG-15: drop a workspace template id that no longer exists.
        templateId: current.templateId && !stillThere ? null : current.templateId,
      }
    }, '圖片模板')

    // Back from the Threads / Instagram OAuth page
    const params = new URLSearchParams(window.location.search)
    if (params.has('connected') || params.has('connect_error')) {
      const platform = PLATFORM_NAME[params.get('platform') || params.get('connected')] || params.get('connected')
      if (params.has('connected')) notify('已連結帳號', `${platform} 已完成授權，可以發布了。`)
      else notify('連結沒有完成', `${platform || ''} ${params.get('connect_error')}`)
      patch({ page: 'settings' })
      window.history.replaceState(null, '', window.location.pathname)
    }
    return () => {
      alive = false
    }
  }, [fail, notify, patch])

  const studio = useMemo(() => {
    const busy = (label) => patch({ busy: label })
    const idle = () => patch({ busy: null })
    const realPlatforms = () => stateRef.current.platforms.map((name) => REAL_PLATFORMS[name]).filter(Boolean)
    const editable = () => {
      const status = activeDraft(stateRef.current)?.status
      if (status && status !== '草稿') {
        notify('這則不能再修改', '待審核和已核准要先退回成草稿。')
        return false
      }
      return true
    }

    const save = async () => {
      const current = stateRef.current
      const post = await api.savePost(current.activeId, patchBody(current))
      upsert(post)
      return post
    }

    const exportAndUpload = async (id) => {
      const current = stateRef.current
      const style = STYLES[current.style] || STYLES[0]
      const board = document.querySelector('.artboard')
      const blob = await exportCard({
        style,
        background: cardBackground(current),
        credit: cardCredit(current),
        company: current.company,
        title: current.title,
        subtitle: current.subtitle,
        description: current.description,
        font: current.font,
        layout: current.layout,
      }, board?.offsetWidth)
      await api.uploadImage(id, blob, 'exported')
    }

    const afterGeneration = (post) => (post.status === 'editing' ? 'edit' : 'write')
    const generationDone = (post) => post.status !== 'generating'
    const reportGeneration = (post) => {
      const stopped = followRef.current.cancelled || /停止/.test(post.generation_error || '')
      if (stopped) {
        notify('已停止生成', post.status === 'editing' ? '保留原本的內容。' : '可以換個方向再試。')
      } else if (post.status === 'editing') {
        const note = post.canvas_json?.image_note
        notify(note ? '初稿完成（圖片有調整）' : '初稿完成', note || 'AI 已寫好 Threads / IG / LinkedIn 文案與圖卡，可以開始編輯。')
      } else notify('生成失敗', post.generation_error || '請再試一次，或換一個方向。')
    }

    const designOptions = () => {
      const current = stateRef.current
      let templateId = current.templateId || null
      // BUG-15: missing template → fall back to AI background instead of failing generation.
      if (templateId && !templateOf(current, templateId)) {
        templateId = null
        patch({ templateId: null })
        notify('這張模板已經刪除', '改用 AI 底圖繼續生成。')
      }
      return {
        style: current.style,
        layout: layoutName(current.layout),
        template_id: templateId,
        // the news article this post is based on; its picture is used per imageMode (photo / blend / ai)
        reference: current.reference || null,
        image_mode: current.reference ? current.imageMode : 'ai',
        language: current.language || 'zh',
      }
    }

    return {
      state,
      user,
      notify,
      patch,
      logout: onLogout,
      refreshPosts,
      refreshAccounts,
      navigate(page) {
        patch({ page })
        if (['library', 'review', 'calendar'].includes(page)) refreshPosts()
        if (page === 'settings') refreshAccounts()
      },
      goStage(stage) {
        if (stage === 'edit' && !state.activeId) {
          notify('還沒有內容', '先生成初稿。')
          return
        }
        if (!stageEnabled(state, stage)) {
          notify('這個階段還沒到', '送交之後才能審核，核准之後才能發布。')
          return
        }
        patch({ stage, page: 'workspace' })
      },
      startFresh() {
        const current = stateRef.current
        const templateOk = templateOf(current, current.templateId)
        patch({
          page: 'workspace', stage: 'write', activeId: null, series: [], candidates: [],
          title: '', subtitle: '', description: '', content: '', igCaption: '', linkedinCaption: '', canvas: null, background: null,
          reference: null, credit: null, imageNote: null,
          // Keep a still-valid workspace template; drop deleted ones so new posts can generate.
          templateId: templateOk ? current.templateId : null,
        })
      },

      // ---------- write: goal → 3 directions → generate
      async generate() {
        const current = stateRef.current
        if (current.busy) return
        if (!current.prompt.trim()) {
          notify('先寫主題', '告訴 AI 這篇要講什麼。')
          return
        }
        busy('candidates')
        const controller = new AbortController()
        abortRef.current = controller
        try {
          const { candidates } = await api.candidates(current.prompt, current.tone, controller.signal)
          patch({
            candidates, series: [], activeId: null, stage: 'write', content: '', igCaption: '', linkedinCaption: '',
            title: '', subtitle: '', description: '', background: null, credit: null, imageNote: null,
          })
          notify('AI 提出了 3 個方向', '挑一個，AI 就會寫文案並產生圖卡。')
        } catch (error) {
          if (isAbort(error)) notify('已停止', '可以修改主題後再產生。')
          else fail(error, '產生方向失敗')
        } finally {
          abortRef.current = null
          idle()
        }
      },
      // 「停止」: abort the pending request, or ask the backend to stop the generating post.
      async stop() {
        if (abortRef.current) {
          abortRef.current.abort()
          return
        }
        const { id, cancelled } = followRef.current
        if (!id || cancelled) return
        followRef.current.cancelled = true
        try {
          await api.cancel(id) // the stream then ends with the post out of `generating`
        } catch (error) {
          followRef.current.cancelled = false
          if (error.status !== 409) fail(error, '停不下來') // 409: it finished first
        }
      },
      async pickCandidate(candidate) {
        const current = stateRef.current
        if (current.busy) return
        busy('generating')
        try {
          const post = await api.createPost({
            goal: current.prompt,
            tone: current.tone,
            audience: current.audience,
            candidates: current.candidates,
            selected: candidate,
            ...designOptions(),
          })
          upsert(post, { load: 'write' })
          patch({ candidates: [], series: [] })
          const done = await follow(post.id, { load: afterGeneration })
          reportGeneration(done)
        } catch (error) {
          fail(error, '生成失敗')
        } finally {
          idle()
        }
      },
      async runBatch(count) {
        const current = stateRef.current
        if (current.busy) return
        if (!current.prompt.trim()) {
          notify('先寫主題', '系列會從同一個主題延伸。')
          return
        }
        busy('series')
        try {
          const { candidates } = await api.candidates(current.prompt, current.tone)
          const picked = candidates.slice(0, count)
          const posts = await Promise.all(picked.map((selected) => api.createPost({
            goal: current.prompt, tone: current.tone, audience: current.audience, candidates, selected, ...designOptions(),
          })))
          posts.forEach((post) => upsert(post))
          patch({ series: posts.map((post) => post.id), candidates: [], activeId: null })
          notify('系列生成中', `${posts.length} 則同時在生成，完成後點一則就能編輯。`)
          await Promise.all(posts.map((post) => poll(post.id, generationDone)))
          notify('系列完成', '點一則載入，再按「下一步，去編輯」。')
        } catch (error) {
          fail(error, '系列生成失敗')
        } finally {
          idle()
        }
      },
      openSeries(item) {
        if (item.status === '生成中') {
          notify('還在生成', '等它完成再打開。')
          return
        }
        patch(withoutUndefined(editorFields(item, 'write')))
      },

      // ---------- edit
      async rewrite(mode) {
        if (!editable() || stateRef.current.busy || !stateRef.current.activeId) return
        busy('generating')
        try {
          await save()
          const post = await api.regenerate(stateRef.current.activeId, { mode, ...designOptions() })
          upsert(post)
          const done = await follow(post.id, { load: afterGeneration })
          if (!followRef.current.cancelled && done.status === 'editing') {
            notify('新版本完成', `這是第 ${done.versions?.length || 1} 版，可用「‹ ›」切回之前的版本。`)
          } else {
            reportGeneration(done)
          }
        } catch (error) {
          fail(error, '重寫失敗')
        } finally {
          idle()
        }
      },
      // Load one of the AI versions (posts.versions) into the editor. Not saved until 存成草稿 / 送審.
      showVersion(index) {
        const item = activeDraft(stateRef.current)
        const version = item?.post?.versions?.[index]
        if (!version || !editable()) return
        const view = toDraft({
          ...item.post,
          title: version.title,
          caption_threads: version.caption_threads,
          caption_instagram: version.caption_instagram,
          caption_linkedin: version.caption_linkedin,
          canvas_json: version.canvas_json,
        })
        const fields = editorFields(view, 'edit')
        patch({
          title: fields.title,
          subtitle: fields.subtitle,
          description: fields.description,
          content: fields.content,
          igCaption: fields.igCaption,
          linkedinCaption: fields.linkedinCaption,
          canvas: fields.canvas,
          background: fields.background,
          credit: fields.credit,
          imageNote: fields.imageNote,
          layout: fields.layout,
          style: fields.style,
          font: fields.font,
          templateId: fields.templateId,
          themeName: fields.themeName,
          versionId: version.id,
        })
      },
      // AI 微調: one chat turn → {reply, ...changed fields}. Errors other than login are for the caller.
      async adjust(instruction, history, signal) {
        const current = stateRef.current
        if (!current.activeId || !editable()) return null
        try {
          return await api.adjust(current.activeId, {
            instruction,
            history,
            current: {
              title: current.title,
              subtitle: current.subtitle,
              threads: current.content,
              instagram: current.igCaption,
              linkedin: current.linkedinCaption,
              style: current.style,
              font: current.font,
              palettes: STYLES.map((item) => item[2]),
            },
          }, signal)
        } catch (error) {
          if (error instanceof AuthError) {
            onLogout()
            return null
          }
          throw error
        }
      },
      // Put AI 微調 changes into the editor; returns the old values so the turn can be undone.
      applyChanges(changes) {
        const current = stateRef.current
        const fields = {
          title: 'title', subtitle: 'subtitle', threads: 'content', instagram: 'igCaption', linkedin: 'linkedinCaption', style: 'style', font: 'font',
        }
        const next = {}
        const before = {}
        for (const [key, field] of Object.entries(fields)) {
          if (changes[key] === undefined) continue
          next[field] = changes[key]
          before[field] = current[field]
        }
        if (next.style !== undefined) {
          next.themeName = STYLES[next.style]?.[2] || current.themeName
          before.themeName = current.themeName
        }
        patch(next)
        return before
      },
      async saveDraft() {
        if (!editable() || !stateRef.current.activeId) return
        busy('saving')
        try {
          await save()
          notify('已存成草稿', '已存到資料庫，可在內容資料庫繼續編輯。')
        } catch (error) {
          fail(error, '儲存失敗')
        } finally {
          idle()
        }
      },
      async submitReview() {
        const current = stateRef.current
        if (!editable() || current.busy || !current.activeId) return
        const platforms = realPlatforms()
        if (!platforms.length) {
          notify('還沒選平台', '勾選 Threads、Instagram 或 LinkedIn（X、Telegram 只是示範）。')
          return
        }
        busy('submitting')
        try {
          await save()
          try {
            await exportAndUpload(current.activeId)
          } catch (error) {
            // QA-N01: do not submit a card that failed to export — publish would miss the overlay text.
            notify('還不能送審', `圖卡匯出失敗：${error.message || '請再試一次'}。修好後再送審。`, { sticky: true })
            return
          }
          const post = await api.submit(current.activeId, platforms)
          upsert(post, { load: 'review' })
          notify('已送交審核', `內容已鎖定。將發布到：${platforms.map((p) => PLATFORM_NAME[p]).join('、')}。`)
        } catch (error) {
          fail(error, '還不能送審')
        } finally {
          idle()
        }
      },

      // ---------- review
      async approve() {
        const item = activeDraft(stateRef.current)
        if (!item || item.status !== '待審核') {
          notify('沒有待審內容', '請先從編輯階段送交審核。')
          return
        }
        try {
          upsert(await api.approve(item.id), { load: 'publish' })
          notify('審核通過', '現在可以直接發布或排程。')
        } catch (error) {
          fail(error, '核准失敗')
        }
      },
      async returnToDraft(id) {
        try {
          const post = await api.reject(id)
          upsert(post, { load: 'edit' })
          notify('已退回草稿', '可以再修改。改完要重新送審。')
        } catch (error) {
          fail(error, '不能退回')
        }
      },

      // ---------- publish
      async publish(id, when) {
        if (stateRef.current.busy) return false
        try {
          if (when !== '現在') {
            if (new Date(when).getTime() <= Date.now()) {
              notify('時間已經過了', '排程請選現在之後的時間。')
              return false
            }
            upsert(await api.schedule(id, withLocalOffset(when)))
            patch({ page: 'calendar' })
            notify('已加入排程', `時間到後端會自動發布（後端要保持執行）。`)
            return true
          }
          busy('publishing')
          upsert(await api.publish(id), { load: 'publish' })
          notify('發布中', '正在送到平台，約需 10–30 秒。')
          const done = await poll(id, (post) => post.status !== 'publishing', { load: () => 'publish' })
          const failed = (done.publications || []).filter((p) => p.status === 'failed')
          if (done.status === 'published') notify('已發布', '可以在發布結果點連結查看。')
          else notify(done.status === 'partially_published' ? '部分平台失敗' : '發布失敗', failed.map((p) => `${PLATFORM_NAME[p.platform]}：${p.error_message}`).join('；'))
          return true
        } catch (error) {
          fail(error, '發布失敗')
          return false
        } finally {
          idle()
        }
      },
      async retry(id, confirmUnpublished = []) {
        // QA-N02: if the backend cannot tell whether a platform already posted, ask before retrying.
        let confirmed = confirmUnpublished
        for (;;) {
          busy('publishing')
          try {
            upsert(await api.retry(id, confirmed.length ? { confirm_unpublished: confirmed } : {}), { load: 'publish' })
            const done = await poll(id, (post) => post.status !== 'publishing', { load: () => 'publish' })
            notify(done.status === 'published' ? '重試成功' : '仍有平台失敗', '詳情看發布結果。')
            return
          } catch (error) {
            const platforms = error?.code === 'publish_uncertain' ? (error.detail?.platforms || []) : []
            if (platforms.length && !confirmed.length) {
              idle()
              const names = platforms.map((p) => PLATFORM_NAME[p] || p).join('、')
              const ok = window.confirm(
                `無法確認 ${names} 是否已發出去。\n\n若你已到平台確認「沒有這則貼文」，按「確定」會再試一次；若已經有貼文，按「取消」避免重複發布。`,
              )
              if (ok) {
                confirmed = platforms
                continue
              }
              notify('已取消重試', `請先到 ${names} 確認有沒有貼文。`, { sticky: true })
              return
            }
            fail(error, '重試失敗')
            return
          } finally {
            idle()
          }
        }
      },
      async reopen(id) {
        try {
          upsert(await api.reopen(id), { load: 'edit' })
          notify('已回到草稿', '改完要重新送審。')
        } catch (error) {
          fail(error, '不能重新編輯')
        }
      },
      async cancelSchedule(id) {
        try {
          upsert(await api.cancelSchedule(id))
          notify('已取消排程', '內容回到已核准，資料庫仍保留。')
        } catch (error) {
          fail(error, '取消排程失敗')
        }
      },

      // ---------- library
      async openItem(item) {
        try {
          const post = await api.getPost(item.id)
          const draft = toDraft(post)
          upsert(post, { load: STAGE_OF[draft.status] || 'publish' })
          if (isBusy(post.status)) {
            const done = await poll(post.id, (p) => !isBusy(p.status), {
              load: (p) => STAGE_OF[toDraft(p).status] || 'publish',
            })
            if (post.status === 'generating') reportGeneration(done)
          }
        } catch (error) {
          fail(error, '打開失敗')
        }
      },
      async deleteDraft(id) {
        if (!window.confirm('確定刪除這則貼文？刪了就不能復原。')) return
        try {
          await api.deletePost(id)
          setState((current) => ({
            ...current,
            drafts: current.drafts.filter((d) => d.id !== id),
            series: current.series.filter((s) => s !== id),
            activeId: current.activeId === id ? null : current.activeId,
            stage: current.activeId === id ? 'write' : current.stage,
          }))
          notify('已刪除', '這則還沒送出，所以可以刪。')
        } catch (error) {
          fail(error, '不能刪除')
        }
      },

      // ---------- discover: real news search with lead pictures (POST /api/research)
      async searchNews(query) {
        const clean = (query ?? stateRef.current.research.query).trim()
        if (!clean) {
          notify('先輸入關鍵字', '例如：AI 新創、生成式 AI 商業化。')
          return
        }
        setState((current) => ({ ...current, research: { ...current.research, query: clean, loading: true, error: null } }))
        try {
          const { results, backend } = await api.research(clean)
          setState((current) => ({ ...current, research: { query: clean, results, backend, loading: false, error: null } }))
          if (!results.length) notify('沒有找到新聞', '換個關鍵字試試。')
        } catch (error) {
          setState((current) => ({ ...current, research: { ...current.research, loading: false, error: error.message } }))
          fail(error, '搜尋失敗')
        }
      },
      // Base the next post on an article. mode: photo (use its picture) / blend (AI 融合) / ai (text only).
      useSource(source, mode = source.image_url ? 'photo' : 'ai') {
        const current = stateRef.current
        const facts = [source.summary, source.source && `（${source.source}${source.published ? `，${source.published}` : ''}）`].filter(Boolean).join('')
        patch({
          page: 'workspace',
          stage: 'write',
          activeId: null,
          series: [],
          candidates: [],
          reference: source,
          imageMode: source.image_url ? mode : 'ai',
          credit: null,
          imageNote: null,
          prompt: `參考「${source.title}」，為${current.audience}撰寫一篇${current.tone}貼文。重點：${facts}`.slice(0, 2000),
        })
        notify('已帶入參考資料', mode === 'ai' || !source.image_url ? '主題已更新，按「產生 3 個方向」。' : '主題與新聞圖片都帶入了，按「產生 3 個方向」。')
      },
      // Attach an article found from the write stage without touching the topic the user typed.
      attachReference(source, mode = source.image_url ? 'photo' : 'ai') {
        if (!editable()) return
        const resolved = source.image_url ? mode : 'ai'
        patch({ reference: source, imageMode: resolved })
        // BUG-04: tip must follow the chosen mode, not merely whether the article has a picture.
        const tip = resolved === 'photo'
          ? '產生時會用這張照片做圖卡，也會引用它的內容。'
          : resolved === 'blend'
            ? '產生時會把照片與品牌風格融合，並引用內容。'
            : '產生時只會引用它的內容，不會用這張照片。'
        notify('已加入參考新聞', tip)
      },
      setImageMode(imageMode) {
        if (!editable()) return
        patch({ imageMode })
      },
      clearReference() {
        if (!editable()) return
        patch({ reference: null, imageMode: 'photo' })
      },

      // ---------- design & templates
      moveLayout(layout) {
        if (!editable()) return
        patch({ layout })
      },
      applyTemplate(index, tone) {
        // BUG-10: locked posts (pending review / approved / …) must keep the submitted card.
        if (stateRef.current.activeId && !editable()) return
        patch({
          style: index,
          templateId: null,
          background: null,
          themeName: STYLES[index][2],
          tone: tone || stateRef.current.tone,
          page: 'workspace',
          stage: stateRef.current.activeId ? 'edit' : stateRef.current.stage,
        })
        notify('已套用版型', `${STYLES[index][2]}。下次生成或目前的草稿都會用這個配色。`)
      },
      async addTemplate(file, name) {
        if (!file) return
        if (!['image/png', 'image/jpeg'].includes(file.type)) {
          notify('格式不支援', '圖片模板只接受 PNG 或 JPEG。')
          return
        }
        if (file.size > 8 * 1024 * 1024) {
          notify('檔案太大', '圖片模板最大 8 MB。')
          return
        }
        try {
          const row = await api.uploadTemplate(file, name.trim())
          setState((current) => ({ ...current, templates: [{ id: row.id, name: row.name, url: row.public_url }, ...current.templates] }))
          notify('已上傳圖片模板', `${row.name}。建議用 1:1 正方形，文字留白處要夠。`)
        } catch (error) {
          fail(error, '上傳模板失敗')
        }
      },
      async removeTemplate(id) {
        const item = templateOf(stateRef.current, id)
        if (!item) return
        try {
          await api.deleteTemplate(id)
          setState((current) => ({
            ...current,
            templates: current.templates.filter((tpl) => tpl.id !== id),
            templateId: current.templateId === id ? null : current.templateId,
            removedTemplates: { ...current.removedTemplates, [id]: item.url },
          }))
          notify('已移除模板', '已經用這張模板的內容不受影響。')
        } catch (error) {
          fail(error, '移除模板失敗')
        }
      },
      pickTemplate(id) {
        // BUG-10: applying a template while reviewing would change the preview, not the locked export.
        if (stateRef.current.activeId && !editable()) return
        const item = id ? templateOf(stateRef.current, id) : null
        patch({
          templateId: item ? item.id : null,
          background: item ? item.url : null,
          page: 'workspace',
          stage: stateRef.current.activeId ? 'edit' : stateRef.current.stage,
        })
        notify(item ? '已套用圖片模板' : '已改回 AI 底圖', item ? `${item.name}。生成時不會再產 AI 底圖。` : '下次生成會由 AI 產底圖。')
      },

      // ---------- feedback & settings
      async remember(rating) {
        const current = stateRef.current
        const entry = { rating, text: current.title || current.content.slice(0, 42), time: '剛剛' }
        patch({ feedback: [entry, ...current.feedback] })
        if (!current.activeId) return
        try {
          await api.feedback(current.activeId, RATING[rating])
          notify('已記下這次回饋', '存到資料庫，之後可用來調整語氣與版型偏好。')
        } catch (error) {
          fail(error, '回饋沒有存到')
        }
      },
      async saveProfile() {
        const current = stateRef.current
        try {
          await api.putSettings({ default_tone: current.tone, default_audience: current.audience, brand_name: current.company })
          notify('已儲存偏好', '下次登入會沿用。')
        } catch (error) {
          fail(error, '儲存偏好失敗')
        }
      },
      // BUG-18 / BUG-13: brand name blur must not rewrite default tone from the open post.
      async saveBrand() {
        try {
          await api.putSettings({ brand_name: stateRef.current.company })
        } catch (error) {
          fail(error, '品牌名稱沒有存到')
        }
      },
      async saveDefaultTone(tone) {
        patch({ tone })
        try {
          await api.putSettings({ default_tone: tone })
        } catch (error) {
          fail(error, '預設語氣沒有存到')
        }
      },
      async addWord(word) {
        const clean = word.trim()
        const current = stateRef.current
        if (!clean || current.sensitive.includes(clean)) return
        const sensitive = [...current.sensitive, clean]
        patch({ sensitive })
        try {
          await api.putSettings({ sensitive_words: sensitive })
        } catch (error) {
          fail(error, '敏感詞沒有存到')
        }
      },
      async removeWord(word) {
        const sensitive = stateRef.current.sensitive.filter((item) => item !== word)
        patch({ sensitive })
        try {
          await api.putSettings({ sensitive_words: sensitive })
        } catch (error) {
          fail(error, '敏感詞沒有存到')
        }
      },
      togglePlatform(name, { asDefault = false } = {}) {
        const { platforms } = stateRef.current
        const next = platforms.includes(name) ? platforms.filter((item) => item !== name) : [...platforms, name]
        patch({ platforms: next })
        if (!asDefault) return
        const ids = next.map((label) => REAL_PLATFORMS[label]).filter(Boolean)
        api.putSettings({ default_platforms: ids }).catch((error) => fail(error, '預設平台沒有存到'))
      },
      async connectAccount(platform) {
        try {
          const result = await api.connect(platform)
          if (result.mock) {
            await refreshAccounts()
            notify('已綁定示範帳號', '後端是模擬發布模式（MOCK_PUBLISH=true）。')
            return
          }
          window.location.href = result.url
        } catch (error) {
          fail(error, '連結失敗')
        }
      },
      async disconnectAccount(platform) {
        try {
          await api.disconnect(platform)
          await refreshAccounts()
          notify('已解除綁定', `${PLATFORM_NAME[platform]} 的授權已從後端移除。`)
        } catch (error) {
          fail(error, '解除綁定失敗')
        }
      },
    }
  }, [state, user, notify, patch, onLogout, refreshPosts, refreshAccounts, fail, upsert, poll, follow])

  const Page = PAGES[state.page] || WorkspacePage
  const active = activeDraft(state)
  const health = state.health
  const note = !health
    ? '連線後端中…'
    : health.error
      ? '後端未連線，請先啟動服務'
      : `${health.ai === 'rap' ? 'AI 文案' : '模擬文案'} · ${health.image === 'fal' ? 'FLUX 圖' : '漸層圖'} · ${health.publish === 'live' ? '正式發布' : '模擬發布'}`

  return (
    <StudioContext.Provider value={studio}>
      <Shell state={state} user={user} onNavigate={studio.navigate} onLogout={onLogout}>
        <Top kicker="Orbit Studio" title={pageTitle(state.page)} note={note}>
          {state.page === 'workspace' && active ? (
            <span className="chip">{active.status}</span>
          ) : null}
        </Top>
        <Page />
      </Shell>
      {toast ? (
        <div className={toast.sticky ? 'toast sticky' : 'toast'} role="status">
          <b>{toast.title}</b>
          <span className="toast-text">{toast.text}</span>
          {toast.sticky ? (
            <button type="button" className="toast-ok" onClick={() => setToast(null)}>知道了</button>
          ) : null}
        </div>
      ) : null}
    </StudioContext.Provider>
  )
}
