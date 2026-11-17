import { useState } from 'react'
import { MENU, MENU_MORE, MENU_PRIMARY, reviewCount } from '../studio.js'

function NavButton({ id, label, active, badge, onClick }) {
  return (
    <button type="button" className={active ? 'active' : ''} onClick={onClick}>
      {label}
      {badge ? <small>{badge}</small> : null}
    </button>
  )
}

export function Shell({ state, user, onNavigate, onLogout, children }) {
  const count = reviewCount(state)
  const inMore = MENU_MORE.includes(state.page)
  const [moreOpen, setMoreOpen] = useState(inMore)
  const byId = Object.fromEntries(MENU)

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <div className="mark" />
          <div>
            <b>orbit.studio</b>
            <span>內容工作台</span>
          </div>
        </div>
        <nav className="nav">
          {MENU_PRIMARY.map((id) => (
            <NavButton
              key={id}
              id={id}
              label={byId[id]}
              active={state.page === id}
              badge={id === 'review' && count > 0 ? count : null}
              onClick={() => onNavigate(id)}
            />
          ))}
          <button
            type="button"
            className={moreOpen || inMore ? 'nav-more on' : 'nav-more'}
            onClick={() => setMoreOpen((open) => !open)}
          >
            更多
            <span aria-hidden="true">{moreOpen || inMore ? '▾' : '▸'}</span>
          </button>
          {(moreOpen || inMore) ? (
            <div className="nav-sub">
              {MENU_MORE.map((id) => (
                <NavButton
                  key={id}
                  id={id}
                  label={byId[id]}
                  active={state.page === id}
                  onClick={() => onNavigate(id)}
                />
              ))}
            </div>
          ) : null}
        </nav>
        <div className="side-foot">
          <div className="who">
            <div className="avatar">{(user?.email || '?').slice(0, 2).toUpperCase()}</div>
            <div style={{ minWidth: 0 }}>
              <b style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis' }}>{user?.email}</b>
              <button type="button" className="link" onClick={onLogout}>登出</button>
            </div>
          </div>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  )
}

export function Top({ kicker, title, note, children }) {
  return (
    <header className="top">
      <div>
        <div className="eyebrow">{kicker}</div>
        <h1>{title}</h1>
        {note ? <p>{note}</p> : null}
      </div>
      {children ? <div className="chips">{children}</div> : null}
    </header>
  )
}

export function Modal({ title, desc, children, onClose, actions }) {
  return (
    <div className="overlay" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <h2>{title}</h2>
        {desc ? <p className="sub">{desc}</p> : null}
        {children}
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>關閉</button>
          {actions}
        </div>
      </div>
    </div>
  )
}
