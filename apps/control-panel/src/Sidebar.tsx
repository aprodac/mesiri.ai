// SA-19 / SA-20 / SA-21: all of the control panel's navigation.
// Desktop: the sidebar -- logo, "Jump to" (⌘K), screens grouped by job, the
// signed-in admin with Sign out.
// Phones (under 900px, CSS decides): a top bar (logo, page name, search),
// a bottom tab bar for the screens used most, and the same sidebar as a
// slide-in menu behind "More".

import { useEffect, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Building2, LayoutGrid, LogOut, Menu, MessageSquareReply, ScrollText, Search, X } from 'lucide-react';
import { useAuth } from './AuthContext';
import { clearToken } from './api';
import CommandPalette from './CommandPalette';
import { NAV_GROUPS, NAV_ITEMS } from './navigation';
import mark from './assets/mesiri-mark.svg';

const TABS = [
  { to: '/', label: 'Overview', icon: LayoutGrid },
  { to: '/organizations', label: 'Companies', icon: Building2 },
  { to: '/logs', label: 'Logs', icon: ScrollText },
  { to: '/replies', label: 'Replies', icon: MessageSquareReply },
];

/** The screen a path belongs to (a company page belongs to Companies). */
function screenFor(path: string) {
  return (
    NAV_ITEMS.filter((i) => (i.to === '/' ? path === '/' : path === i.to || path.startsWith(`${i.to}/`))).sort(
      (a, b) => b.to.length - a.to.length,
    )[0] ?? NAV_ITEMS[0]
  );
}

export default function Sidebar() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const name = me?.name || 'Super admin';
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
  const current = screenFor(pathname);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      } else if (e.key === 'Escape') setMenuOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Moving to another screen closes the phone menu.
  useEffect(() => setMenuOpen(false), [pathname]);

  // The page behind an open phone menu doesn't scroll.
  useEffect(() => {
    document.body.classList.toggle('menu-open', menuOpen);
    return () => document.body.classList.remove('menu-open');
  }, [menuOpen]);

  const signOut = () => {
    clearToken();
    navigate('/login', { replace: true });
  };

  const brand = (
    <>
      <img src={mark} alt="" className="sb-mark" />
      <span className="sb-word">mesiri</span>
    </>
  );

  return (
    <>
      {/* Phones: top bar */}
      <header className="mb-top">
        <button className="mb-icon" onClick={() => setMenuOpen(true)} aria-label="Open menu">
          <Menu size={20} />
        </button>
        <div className="mb-title">
          <current.icon size={16} strokeWidth={1.75} />
          <span>{current.label}</span>
        </div>
        <button className="mb-icon" onClick={() => setPaletteOpen(true)} aria-label="Jump to a screen">
          <Search size={19} />
        </button>
      </header>

      {menuOpen && <div className="mb-backdrop" onClick={() => setMenuOpen(false)} aria-hidden="true" />}

      <aside className={`sidebar${menuOpen ? ' open' : ''}`} aria-label="Menu">
        <div className="sb-brand">
          {brand}
          <span className="sb-env">Control</span>
          <button className="mb-icon sb-close" onClick={() => setMenuOpen(false)} aria-label="Close menu">
            <X size={19} />
          </button>
        </div>

        <button
          className="sb-search"
          onClick={() => {
            setMenuOpen(false);
            setPaletteOpen(true);
          }}
        >
          <Search size={14} />
          <span>Jump to…</span>
          <kbd>⌘K</kbd>
        </button>

        <nav className="sb-nav" aria-label="Control panel">
          {NAV_GROUPS.map((group) => (
            <div key={group.label ?? 'home'} className="sb-group">
              {group.label && <div className="sb-label">{group.label}</div>}
              {group.items.map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                  <Icon size={16} strokeWidth={1.75} />
                  <span>{label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sb-user">
          <span className="sb-avatar">{initials}</span>
          <div className="sb-user-text">
            <div className="sb-user-name">{name}</div>
            <div className="sb-user-role">Super admin</div>
          </div>
          <button className="sb-signout" onClick={signOut} title="Sign out" aria-label="Sign out">
            <LogOut size={15} />
          </button>
        </div>
      </aside>

      {/* Phones: bottom tabs */}
      <nav className="mb-tabs" aria-label="Main screens">
        {TABS.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `mb-tab${isActive ? ' on' : ''}`}>
            <Icon size={20} strokeWidth={1.75} />
            <span>{label}</span>
          </NavLink>
        ))}
        <button className={`mb-tab${menuOpen ? ' on' : ''}`} onClick={() => setMenuOpen(true)}>
          <Menu size={20} strokeWidth={1.75} />
          <span>More</span>
        </button>
      </nav>

      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </>
  );
}
