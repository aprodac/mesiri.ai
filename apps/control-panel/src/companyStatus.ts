// Shared by the companies list (SA-02) and the company page's plan card
// (SS-10): how a company's status and setup progress read. The ticks
// component is SetupSteps.tsx.

export interface Setup {
  has_team: boolean;
  has_site: boolean;
  first_update_at: string | null;
  first_dpr_sent_at: string | null;
}

export interface Company {
  id: string;
  name: string;
  effective_status: string;
  trial_days_left: number | null;
  trial_ends_at: string | null;
  trial_started_at?: string | null;
  converted_at?: string | null;
  status?: string;
  signup_source: string;
  created_at: string | null;
  setup: Setup;
  open_branding_requests?: number;
  // SA-10: the owner asked to continue with Mesiri (closed by convert / extend);
  // a trial ended longer ago than the data is kept (flag only, nothing auto-deleted).
  open_continue_requests?: number;
  continue_requested_at?: string | null;
  eligible_for_deletion?: boolean;
}

export const FILTERS = ['all', 'trial', 'active', 'expired', 'suspended'] as const;
export type Filter = (typeof FILTERS)[number];

export const FILTER_LABELS: Record<Filter, string> = {
  all: 'All',
  trial: 'Trial',
  active: 'Active',
  expired: 'Expired',
  suspended: 'Suspended',
};

export const SOURCE_LABELS: Record<string, string> = {
  superadmin: 'Superadmin',
  whatsapp: 'WhatsApp',
  web: 'Web',
  api: 'API',
};

export const STATUS_BADGE: Record<string, string> = {
  trial: 'badge-info',
  active: 'badge-success',
  expired: 'badge-warning',
  suspended: 'badge-error',
};

export function shortDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function statusText(c: Company): string {
  if (c.effective_status === 'trial') {
    if (c.trial_days_left === null) return 'Trial';
    if (c.trial_days_left <= 1) return 'Trial · last day';
    return `Trial · ${c.trial_days_left} days left`;
  }
  return FILTER_LABELS[c.effective_status as Filter] ?? c.effective_status;
}
