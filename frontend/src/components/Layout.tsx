import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { BookOpen, LayoutDashboard, Menu, ScanSearch, ShieldCheck, Stamp, X } from 'lucide-react'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/detect', label: 'Forgery Detection', icon: ScanSearch },
  { to: '/watermark', label: 'Watermark Studio', icon: Stamp },
  { to: '/how-it-works', label: 'How It Works', icon: BookOpen },
]

export default function Layout() {
  const [open, setOpen] = useState(false)
  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-1 p-3">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to} to={to} end={end} onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
              isActive ? 'bg-ink-700 text-white' : 'text-slate-300 hover:bg-ink-800 hover:text-white'}`}
        >
          <Icon size={18} aria-hidden /> {label}
        </NavLink>
      ))}
    </nav>
  )
  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 flex-col bg-ink-900 lg:flex">
        <Brand />
        {nav}
        <p className="mt-auto p-5 text-xs leading-relaxed text-slate-400">
          Heuristic analysis tool. Results are indicators for review, not proof of authenticity or tampering.
        </p>
      </aside>
      <header className="sticky top-0 z-20 flex items-center justify-between bg-ink-900 px-4 py-3 lg:hidden">
        <Brand compact />
        <button className="rounded-lg p-2 text-slate-200 hover:bg-ink-800" aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </header>
      {open && <div className="z-10 bg-ink-900 lg:hidden">{nav}</div>}
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto max-w-6xl"><Outlet /></div>
      </main>
    </div>
  )
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`flex items-center gap-2.5 ${compact ? '' : 'px-5 py-5'}`}>
      <ShieldCheck className="text-accent-400" size={26} aria-hidden />
      <div>
        <div className="text-base font-bold leading-none text-white">ImageGuard</div>
        {!compact && <div className="mt-1 text-[11px] text-slate-400">Forgery detection &amp; watermarking</div>}
      </div>
    </div>
  )
}
