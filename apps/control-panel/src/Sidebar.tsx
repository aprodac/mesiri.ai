// SA-19 / SA-20: the control panel's sidebar -- the Mesiri logo, "Jump to"
// (⌘K, see CommandPalette), the screens grouped by the job they do, and the
// signed-in admin with Sign out.

import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { LogOut, Search } from 'lucide-react';
import { useAuth } from './AuthContext';
import { clearToken } from './api';
import CommandPalette from './CommandPalette';
import { NAV_GROUPS } from './navigation';
import mark from './assets/mesiri-mark.svg';

export default function Sidebar() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const name = me?.name || 'Super admin';
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const signOut = () => {
    clearToken();
    navigate('/login', { replace: true });
  };

  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <img src={mark} alt="" className="sb-mark" />
        <span className="sb-word">mesiri</span>
        <span className="sb-env">Control</span>
      </div>

      <button className="sb-search" onClick={() => setPaletteOpen(true)}>
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

      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </aside>
  );
}
