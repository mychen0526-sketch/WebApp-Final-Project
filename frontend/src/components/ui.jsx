import { MENU, reviewCount } from '../studio.js'

export function Shell({ state, onNavigate, children }) {
  const count = reviewCount(state)
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
          {MENU.map(([id, label]) => (
            <button key={id} className={state.page === id ? 'active' : ''} onClick={() => onNavigate(id)}>
              {label}
              {id === 'review' && count > 0 ? <small>{count}</small> : null}
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="who">
            <div className="avatar">YT</div>
            <div>
              <b>專題展示帳號</b>
              示範模式
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
