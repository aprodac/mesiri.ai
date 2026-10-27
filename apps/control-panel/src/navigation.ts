// SA-19 / SA-20: every control-panel screen, grouped by the job it does.
// One list for the sidebar and the ⌘K palette, so they can't disagree.

import type { LucideIcon } from 'lucide-react';
import {
  Building2,
  Cpu,
  Database,
  FlaskConical,
  Funnel,
  GitBranch,
  IndianRupee,
  LayoutGrid,
  ListChecks,
  ListOrdered,
  MessageSquareReply,
  ScrollText,
  Settings,
  Stamp,
  Tags,
  Timer,
  Users,
} from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** What the screen is for, shown in the ⌘K palette. */
  hint: string;
}

export const NAV_GROUPS: { label: string | null; items: NavItem[] }[] = [
  { label: null, items: [{ to: '/', label: 'Overview', icon: LayoutGrid, hint: 'What needs you today' }] },
  {
    label: 'Customers',
    items: [
      { to: '/organizations', label: 'Companies', icon: Building2, hint: 'Every company, status and setup' },
      { to: '/trials', label: 'Trials', icon: Funnel, hint: 'Trial funnel and conversions' },
      { to: '/branding-requests', label: 'Branding requests', icon: Stamp, hint: 'Letterhead and logo requests' },
    ],
  },
  {
    label: 'WhatsApp',
    items: [
      { to: '/logs', label: 'Assistant logs', icon: ScrollText, hint: 'Every message and what it did' },
      { to: '/replies', label: 'Reply insights', icon: MessageSquareReply, hint: 'Reply time and AI tokens per message' },
      { to: '/test-message', label: 'Test message', icon: FlaskConical, hint: 'Send a message through the pipeline' },
    ],
  },
  {
    label: 'Money and speed',
    items: [
      { to: '/costs', label: 'Costs', icon: IndianRupee, hint: 'AI and WhatsApp spend' },
      { to: '/perf', label: 'Performance', icon: Timer, hint: 'Pipeline stage timings' },
      { to: '/queue-health', label: 'Queue health', icon: ListOrdered, hint: 'Message worker and queue' },
    ],
  },
  {
    label: 'AI and data',
    items: [
      { to: '/providers', label: 'AI providers', icon: Cpu, hint: 'Models and providers' },
      { to: '/workflows', label: 'Workflows', icon: ListChecks, hint: 'Assistant workflows' },
      { to: '/semantic-types', label: 'Semantic types', icon: Tags, hint: 'What messages can mean' },
      { to: '/system-graph', label: 'System graph', icon: GitBranch, hint: 'How the system fits together' },
      { to: '/database', label: 'Database', icon: Database, hint: 'Browse tables, run SQL' },
    ],
  },
  {
    label: 'Admin',
    items: [
      { to: '/users', label: 'Superadmins', icon: Users, hint: 'Who can use this panel' },
      { to: '/settings', label: 'Settings', icon: Settings, hint: 'Platform settings and alerts' },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);
