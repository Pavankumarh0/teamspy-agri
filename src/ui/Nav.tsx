import { useEffect, useState } from 'react'
import { onActiveSection } from '../lib/store'
import { scrollToId } from './scroll'
import { Close, LogoMark, Menu } from './Icons'

export const NAV = [
  { id: 'land', label: 'Your Land', section: 1 },
  { id: 'voice', label: 'Ask Chiguru', section: 2 },
  { id: 'device', label: 'Device', section: 3 },
  { id: 'impact', label: 'Impact', section: 4 },
]

const RAIL = ['Home', 'Your Land', 'Ask Chiguru', 'Device', 'Impact', 'Contact']
const RAIL_IDS = ['top', 'land', 'voice', 'device', 'impact', 'contact']

export function Nav() {
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  useEffect(() => onActiveSection(setActive), [])

  const go = (id: string) => {
    setOpen(false)
    scrollToId(id)
  }

  return (
    <>
      <header className={`nav ${active > 0 ? 'is-scrolled' : ''}`}>
        <a className="brand" href="#top" onClick={(e) => (e.preventDefault(), go('top'))} aria-label="Chiguru home">
          <LogoMark width={30} height={30} />
          <span>Chiguru</span>
        </a>
        <nav className="nav-links glass" aria-label="Primary">
          {NAV.map((n) => (
            <a
              key={n.id}
              href={`#${n.id}`}
              className={active === n.section ? 'is-active' : ''}
              onClick={(e) => (e.preventDefault(), go(n.id))}
            >
              {n.label}
            </a>
          ))}
        </nav>
        <a className="btn btn-sm btn-primary nav-cta" href="#contact" onClick={(e) => (e.preventDefault(), go('contact'))}>
          Get in touch
        </a>
        <button className="menu-btn glass" type="button" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? <Close /> : <Menu />}
        </button>
        <div className="nav-progress" aria-hidden />
      </header>

      <div className={`mobile-menu ${open ? 'is-open' : ''}`} aria-hidden={!open}>
        {[...NAV, { id: 'contact', label: 'Contact', section: 5 }].map((n, i) => (
          <a key={n.id} href={`#${n.id}`} style={{ transitionDelay: `${open ? 80 + i * 60 : 0}ms` }} onClick={(e) => (e.preventDefault(), go(n.id))} tabIndex={open ? 0 : -1}>
            <span>0{i + 1}</span>
            {n.label}
          </a>
        ))}
      </div>

      <aside className="rail" aria-label="Section progress">
        {RAIL.map((label, i) => (
          <button key={label} type="button" className={active === i ? 'is-active' : ''} onClick={() => go(RAIL_IDS[i])} aria-label={`Go to ${label}`}>
            <span className="rail-label">{label}</span>
            <span className="rail-dot" />
          </button>
        ))}
      </aside>
    </>
  )
}
