// SA-19: the control panel's sidebar, grouped by the job each screen does,
// with the signed-in admin and Sign out at the bottom.

import { NavLink, useNavigate } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import {
  Building2,
  Cpu,
  Database,
  FlaskConical,
  Funnel,
  GitBranch,
  IndianRupee,
  LayoutDashboard,
  ListChecks,
  ListOrdered,
  LogOut,
  MessageSquareReply,
  ScrollText,
  Settings,
  Stamp,
  Tags,
  Timer,
  Users,
} from 'lucide-react';
import { useAuth } from './AuthContext';
import { clearToken } from './api';

interface Item {
  to: string;
  label: string;
  icon: LucideIcon;
}

const GROUPS: { label: string | null; items: Item[] }[] = [
  { label: null, items: [{ to: '/', label: 'Overview', icon: LayoutDashboard }] },
  {
    label: 'Customers',
    items: [
      { to: '/organizations', label: 'Companies', icon: Building2 },
      { to: '/trials', label: 'Trials', icon: Funnel },
      { to: '/branding-requests', label: 'Branding requests', icon: Stamp },
    ],
  },
  {
    label: 'WhatsApp',
    items: [
      { to: '/logs', label: 'Assistant Logs', icon: ScrollText },
      { to: '/replies', label: 'Reply Insights', icon: MessageSquareReply },
      { to: '/test-message', label: 'Test Message', icon: FlaskConical },
    ],
  },
  {
    label: 'Money & speed',
    items: [
      { to: '/costs', label: 'Costs', icon: IndianRupee },
      { to: '/perf', label: 'Performance', icon: Timer },
      { to: '/queue-health', label: 'Queue Health', icon: ListOrdered },
    ],
  },
  {
    label: 'AI & data',
    items: [
      { to: '/providers', label: 'AI Providers', icon: Cpu },
      { to: '/workflows', label: 'Workflows', icon: ListChecks },
      { to: '/semantic-types', label: 'Semantic Types', icon: Tags },
      { to: '/system-graph', label: 'System Graph', icon: GitBranch },
      { to: '/database', label: 'Database', icon: Database },
    ],
  },
  {
    label: 'Admin',
    items: [
      { to: '/users', label: 'Superadmins', icon: Users },
      { to: '/settings', label: 'Settings', icon: Settings },
    ],
  },
];

export default function Sidebar() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const initials = (me?.name || 'Admin')
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  const signOut = () => {
    clearToken();
    navigate('/login', { replace: true });
  };

  return (
    <aside className="sidebar">
      <div className="logo-container">
        <div className="logo-icon">
          <Building2 size={17} />
        </div>
        <div>
          <div className="logo-text">Mesiri</div>
          <div className="logo-sub">Control panel</div>
        </div>
      </div>

      <nav className="sb-nav" aria-label="Control panel">
        {GROUPS.map((group) => (
          <div key={group.label ?? 'home'} className="sb-group">
            {group.label && <div className="sb-label">{group.label}</div>}
            {group.items.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                <Icon size={16} strokeWidth={1.9} />
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="sb-user">
        <span className="sb-avatar">{initials}</span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="sb-user-name">{me?.name || 'Super admin'}</div>
          <div className="sb-user-role">Super admin</div>
        </div>
        <button className="sb-signout" onClick={signOut} title="Sign out" aria-label="Sign out">
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  );
}
