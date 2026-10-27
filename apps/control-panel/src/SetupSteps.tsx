import { Check, Circle } from 'lucide-react';
import { shortDate, type Setup } from './companyStatus';

// The four setup ticks (Team, Site, Update, DPR) of a company (SA-02).

function Step({ label, done, title }: { label: string; done: boolean; title: string }) {
  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
        fontSize: '12px',
        marginRight: 'var(--space-3)',
        color: done ? 'var(--success)' : 'var(--neutral-400)',
      }}
    >
      {done ? <Check size={13} /> : <Circle size={11} />}
      {label}
    </span>
  );
}

export default function SetupSteps({ setup }: { setup: Setup }) {
  return (
    // Each tick stays whole; the row wraps when it runs out of room (phones).
    <span style={{ display: 'inline-flex', flexWrap: 'wrap', rowGap: 4, whiteSpace: 'nowrap' }}>
      <Step label="Team" done={setup.has_team} title={setup.has_team ? 'Has people besides the owner' : 'Only the owner so far'} />
      <Step label="Site" done={setup.has_site} title={setup.has_site ? 'Has a site' : 'No site yet'} />
      <Step
        label="Update"
        done={!!setup.first_update_at}
        title={setup.first_update_at ? `First update ${shortDate(setup.first_update_at)}` : 'No site update yet'}
      />
      <Step
        label="DPR"
        done={!!setup.first_dpr_sent_at}
        title={setup.first_dpr_sent_at ? `First DPR sent ${shortDate(setup.first_dpr_sent_at)}` : 'No DPR sent yet'}
      />
    </span>
  );
}
