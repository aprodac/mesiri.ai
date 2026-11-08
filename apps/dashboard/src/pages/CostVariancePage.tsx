import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ChevronRight,
  HardHat,
  Package,
  Ruler,
  TrafficCone,
} from 'lucide-react';
import {
  Callout,
  DprHeader,
  DprSection,
  PageError,
  StatStrip,
  type StatTone,
} from '@/components/dpr-page';
import { CostExportButton } from '@/components/cost/export-button';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '@/lib/AuthContext';
import { formatQuantity, formatRupees, maySeeBoq } from '@/lib/boq';
import {
  fetchProjectVariance,
  type VarianceColour,
  type VarianceDay,
  type VarianceLine,
} from '@/lib/cost';
import { usePageTitle } from '@/lib/page-title';
import { fetchProjects } from '@/lib/projects';
import { useScope } from '@/lib/ScopeContext';
import { COLOUR_DOT, COLOUR_TEXT, COLOUR_WORD } from '@/lib/cost-colours';
import { cn } from '@/lib/utils';

// CC-07: green / amber / red per BOQ line. For a period, each line's labour budget earned by the work measured
// (done x labour rate) against the labour put on the line (CC-05): green when it earned at least what it cost,
// amber within 10%, red below. A line that cannot be judged is grey and says why, never coloured. Worst first.
// Backend: GET /cost/projects/{id}/variance (domains/costing/variance.py).

const TONE: Record<VarianceColour, StatTone> = {
  green: 'good',
  amber: 'warn',
  red: 'bad',
  grey: 'default',
};

function isoDay(d: Date): string {
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
}
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
}
function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('en-IN', {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
      });
}

const PERIODS = [
  {
    key: 'yesterday',
    label: 'Yesterday',
    from: () => daysAgo(1),
    to: () => daysAgo(1),
  },
  {
    key: 'today',
    label: 'Today',
    from: () => daysAgo(0),
    to: () => daysAgo(0),
  },
  {
    key: '7d',
    label: 'Last 7 days',
    from: () => daysAgo(6),
    to: () => daysAgo(0),
  },
  {
    key: '30d',
    label: 'Last 30 days',
    from: () => daysAgo(29),
    to: () => daysAgo(0),
  },
] as const;

/** D-CC4: why a line is its colour for a site engineer: quantities and man-days, never rupees or rates. */
function siteReasonText(l: VarianceLine): string {
  const done = `${formatQuantity(l.done_quantity)} ${l.unit}`;
  const md = `${formatQuantity(l.labour_man_days)} man-days`;
  switch (l.reason) {
    case 'over_budget':
      return `${md} for ${done}: more labour than the BOQ allows for that work.`;
    case 'near_budget':
      return `${md} for ${done}: a little more labour than the BOQ allows, within 10%.`;
    case 'within_budget':
      return `${md} for ${done}: within what the BOQ allows.`;
    case 'labour_no_work':
      return `${md} on this line and no ${l.unit} measured.`;
    case 'no_labour':
      return `${done} measured, but no labour is put on this line yet.`;
    case 'no_labour_rate':
      return 'The BOQ has nothing to compare the labour with on this line yet.';
    case 'no_wage':
      return `${md}: the office has not set the wages, so it cannot be judged.`;
  }
}

/** Why a line is its colour, in the words the GM used ("₹6,400 of labour: was the work done?"). */
function reasonText(l: VarianceLine): string {
  const done = `${formatQuantity(l.done_quantity)} ${l.unit}`;
  const perUnit =
    l.cost_per_unit && l.labour_rate
      ? `${formatRupees(l.cost_per_unit)} per ${l.unit} against the budget ${formatRupees(l.labour_rate)}`
      : '';
  switch (l.reason) {
    case 'over_budget':
      return `${formatRupees(l.labour_cost)} of labour for ${done}: ${perUnit}.`;
    case 'near_budget':
      return `${formatRupees(l.labour_cost)} of labour for ${done}: ${perUnit}, within 10%.`;
    case 'within_budget':
      return `${formatRupees(l.earned_labour)} of work for ${formatRupees(l.labour_cost)} of labour: ${perUnit}.`;
    case 'labour_no_work':
      return `${formatRupees(l.labour_cost)} of labour (${formatQuantity(l.labour_man_days)} man-days) and no ${l.unit} measured on this line.`;
    case 'no_labour':
      return `${done} measured, but no labour is put on this line, so what it cost is not known.`;
    case 'no_labour_rate':
      return 'This BOQ line has no labour rate, so there is nothing to set the labour against.';
    case 'no_wage':
      return `${formatQuantity(l.labour_man_days)} man-days with no wage, so what they cost is not known.`;
  }
}

function Difference({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return (
    <span
      className={cn(
        'font-semibold tabular-nums',
        n < 0 ? 'text-destructive' : 'text-success',
      )}
    >
      {n < 0
        ? `${formatRupees(String(-n))} over`
        : `${formatRupees(String(n))} under`}
    </span>
  );
}

function LineRow({
  line,
  projectId,
  siteView,
}: {
  line: VarianceLine;
  projectId: string;
  siteView: boolean;
}) {
  return (
    <li className="flex gap-3 px-3 py-3">
      <span
        className={cn(
          'mt-1 h-auto w-1 shrink-0 rounded-full',
          COLOUR_DOT[line.colour],
        )}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
          <p className="min-w-0 font-medium">
            <span
              className={cn(
                'mr-2 text-xs font-semibold uppercase tracking-wide',
                COLOUR_TEXT[line.colour],
              )}
            >
              {COLOUR_WORD[line.colour]}
            </span>
            {line.boq_code ? `${line.boq_code} · ` : ''}
            {line.work}
          </p>
          <Difference value={line.difference} />
        </div>
        <p className="text-sm text-muted-foreground">
          {siteView ? siteReasonText(line) : reasonText(line)}
        </p>
        <p className="text-xs text-muted-foreground">
          {line.section ? `${line.section} · ` : ''}
          <span className="tabular-nums">
            Done {formatQuantity(line.done_quantity)} {line.unit}
            {line.earned_labour
              ? ` · earned ${formatRupees(line.earned_labour)}`
              : ''}
            {Number(line.labour_man_days) > 0
              ? ` · ${formatQuantity(line.labour_man_days)} man-days`
              : ''}
            {line.labour_cost
              ? ` · spent ${formatRupees(line.labour_cost)}`
              : ''}
          </span>
          {!siteView && line.reason === 'no_labour' && (
            <>
              {' · '}
              <Link
                to={`/cost/budget?project=${projectId}#labour-to-lines`}
                className="font-medium underline underline-offset-2"
              >
                Put labour on it
              </Link>
            </>
          )}
          {!siteView && line.reason === 'no_labour_rate' && (
            <>
              {' · '}
              <Link
                to={`/projects/${projectId}/boq`}
                className="font-medium underline underline-offset-2"
              >
                Set the rate
              </Link>
            </>
          )}
        </p>
      </div>
    </li>
  );
}

function DayStrip({
  days,
  onPick,
  picked,
}: {
  days: VarianceDay[];
  onPick: (d: string) => void;
  picked: string | null;
}) {
  return (
    <ul
      className="flex gap-2 overflow-x-auto pb-1 [contain:inline-size]"
      aria-label="Each day"
    >
      {days.map((d) => (
        <li key={d.date} className="shrink-0">
          <button
            type="button"
            onClick={() => onPick(d.date)}
            className={cn(
              'flex w-36 flex-col gap-1 rounded-lg border px-3 py-2 text-left hover:bg-muted/60',
              picked === d.date && 'border-primary ring-1 ring-primary',
            )}
          >
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span
                className={cn('size-2 rounded-full', COLOUR_DOT[d.colour])}
                aria-hidden="true"
              />
              {formatDay(d.date)}
            </span>
            <span
              className={cn('text-sm font-semibold', COLOUR_TEXT[d.colour])}
            >
              {COLOUR_WORD[d.colour]}
            </span>
            {d.labour_cost === undefined ? null : d.labour_cost !== null ? (
              <span className="flex flex-col text-xs tabular-nums text-muted-foreground">
                <span>Earned {formatRupees(d.earned_labour)}</span>
                <span>Spent {formatRupees(d.labour_cost)}</span>
              </span>
            ) : (
              <span className="text-xs tabular-nums text-muted-foreground">
                {formatRupees(d.attendance_cost)} of labour, none on a line
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

function ProjectPicker() {
  const projects = useQuery({
    queryKey: ['scope-projects'],
    queryFn: fetchProjects,
  });
  if (projects.isLoading) return <Skeleton className="h-32 rounded-lg" />;
  if ((projects.data ?? []).length === 0)
    return <p className="text-sm text-muted-foreground">No projects yet.</p>;
  return (
    <ul className="divide-y rounded-lg border">
      {(projects.data ?? []).map((p) => (
        <li key={p.id}>
          <Link
            to={`/cost/green-red?project=${p.id}`}
            className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60"
          >
            <span className="flex size-8 items-center justify-center rounded-md bg-muted">
              <TrafficCone className="size-4" />
            </span>
            <span className="flex-1 font-medium">{p.name}</span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function CostVariancePage() {
  const { me } = useAuth();
  const { scope } = useScope();
  const [params, setParams] = useSearchParams();
  usePageTitle('Green / red');
  // D-CC4: a site engineer sees their own site's colours and quantities (the API takes the money out).
  const siteView =
    !maySeeBoq(me?.role) &&
    String(me?.role ?? '').toUpperCase() === 'SITE_ENGINEER';
  const allowed = maySeeBoq(me?.role) || siteView;
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : null;
  const siteId = scope.mode === 'site' ? scope.siteId : undefined;
  const periodKey = params.get('period') ?? '7d';
  const preset = PERIODS.find((p) => p.key === periodKey);
  const dateFrom = params.get('from') ?? (preset ?? PERIODS[2]).from();
  const dateTo = params.get('to') ?? (preset ?? PERIODS[2]).to();
  const q = useQuery({
    queryKey: ['cost', 'variance', projectId, siteId, dateFrom, dateTo],
    queryFn: () =>
      fetchProjectVariance(projectId!, {
        date_from: dateFrom,
        date_to: dateTo,
        site_id: siteId,
      }),
    enabled: allowed && !!projectId,
  });

  const setPeriod = (key: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('period', key);
      next.delete('from');
      next.delete('to');
      return next;
    });
  const pickDay = (day: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('period', 'day');
      next.set('from', day);
      next.set('to', day);
      return next;
    });

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">
          Green / red shows the company's rates and labour cost.
        </p>
        <p className="text-sm text-muted-foreground">
          Only owners, admins, finance and project managers can open it.
        </p>
      </div>
    );
  }
  const title =
    scope.mode === 'site'
      ? `${scope.projectName} · ${scope.siteName}`
      : scope.mode === 'project'
        ? scope.projectName
        : 'Pick a project';
  const header = (
    <DprHeader
      back={
        siteView
          ? { to: '/today', label: 'Today' }
          : { to: '/cost', label: 'Overview' }
      }
      crumb="Cost control"
      title="Green / red"
      date={title}
      action={
        projectId && !siteView ? (
          <CostExportButton
            projectId={projectId}
            projectName={
              scope.mode !== 'portfolio' ? scope.projectName : undefined
            }
            period={{ date_from: dateFrom, date_to: dateTo }}
          />
        ) : undefined
      }
    />
  );
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 pb-8 sm:px-2">
        {header}
        <p className="text-sm text-muted-foreground">
          For each BOQ line: was the labour worth the work measured? Pick a
          project.
        </p>
        <ProjectPicker />
      </div>
    );
  }
  if (q.isError) {
    const status = (q.error as { response?: { status?: number } } | null)
      ?.response?.status;
    if (siteView && status === 422) {
      return (
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
          {header}
          <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
            Pick your site in the bar at the top to see its green / red.
          </p>
        </div>
      );
    }
    return (
      <PageError
        message="Green / red could not be loaded."
        onRetry={() => q.refetch()}
        back={{ to: '/today', label: 'Today' }}
      />
    );
  }
  const v = q.data;
  const single = dateFrom === dateTo;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      {header}
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label="Period"
      >
        {PERIODS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => setPeriod(p.key)}
            aria-pressed={periodKey === p.key}
            className={cn(
              'rounded-full border px-3 py-1 text-sm',
              periodKey === p.key
                ? 'border-primary bg-primary text-primary-foreground'
                : 'hover:bg-muted/60',
            )}
          >
            {p.label}
          </button>
        ))}
        {periodKey === 'day' && (
          <span className="rounded-full border border-primary px-3 py-1 text-sm">
            {formatDay(dateFrom)}
          </span>
        )}
      </div>

      {q.isLoading || !v ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : (
        <>
          {siteView || v.money_hidden ? (
            <StatStrip
              stats={[
                {
                  label: 'Overall',
                  value: COLOUR_WORD[v.summary.colour],
                  tone: TONE[v.summary.colour],
                  icon: TrafficCone,
                  hint: single
                    ? formatDay(dateFrom)
                    : `${formatDay(v.date_from)} – ${formatDay(v.date_to)}`,
                },
                {
                  label: 'Lines',
                  value: `${v.summary.lines.red} red · ${v.summary.lines.amber} amber`,
                  hint: `${v.summary.lines.green} green · ${v.summary.lines.grey} not judged`,
                },
                {
                  label: 'Labour',
                  value: `${formatQuantity(v.labour.man_days)} man-days`,
                  hint: `${formatQuantity(v.labour.not_on_a_line.man_days)} not on a BOQ line`,
                },
              ]}
            />
          ) : (
            <StatStrip
              stats={[
                {
                  label: 'Overall',
                  value: COLOUR_WORD[v.summary.colour],
                  tone: TONE[v.summary.colour],
                  icon: TrafficCone,
                  hint: single
                    ? formatDay(dateFrom)
                    : `${formatDay(v.date_from)} – ${formatDay(v.date_to)}`,
                },
                {
                  label: 'Labour earned',
                  value: formatRupees(v.summary.earned_labour),
                  hint: 'work done × labour rate',
                },
                {
                  label: 'Labour spent',
                  value: formatRupees(v.summary.labour_cost),
                  hint: 'on those lines',
                },
                {
                  label:
                    Number(v.summary.difference ?? 0) < 0 ? 'Over' : 'Under',
                  value:
                    v.summary.difference === null
                      ? '—'
                      : formatRupees(
                          String(Math.abs(Number(v.summary.difference))),
                        ),
                  tone:
                    v.summary.difference === null
                      ? 'default'
                      : Number(v.summary.difference) < 0
                        ? 'bad'
                        : 'good',
                },
                {
                  label: 'Lines',
                  value: `${v.summary.lines.red} red · ${v.summary.lines.amber} amber`,
                  hint: `${v.summary.lines.green} green · ${v.summary.lines.grey} not judged`,
                },
              ]}
            />
          )}

          {!siteView &&
            !v.money_hidden &&
            Number(v.labour.not_on_a_line.cost) > 0 && (
              <Callout
                tone="draft"
                icon={HardHat}
                action={
                  <Link
                    to={`/cost/budget?project=${projectId}#labour-to-lines`}
                    className="shrink-0 text-sm font-medium underline underline-offset-2"
                  >
                    Put it on its lines
                  </Link>
                }
              >
                {formatRupees(v.labour.not_on_a_line.cost)} of labour (
                {formatQuantity(v.labour.not_on_a_line.man_days)} man-days) in
                this period is not on a BOQ line, so no line is coloured by it.
              </Callout>
            )}

          {v.days.length > 1 && (
            <DprSection
              icon={TrafficCone}
              title="Each day"
              meta={v.days.length}
            >
              <DayStrip
                days={v.days}
                onPick={pickDay}
                picked={periodKey === 'day' ? dateFrom : null}
              />
            </DprSection>
          )}

          <DprSection
            icon={Ruler}
            title="BOQ lines, worst first"
            meta={v.lines.length || undefined}
          >
            {v.lines.length === 0 ? (
              <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed px-4 py-6">
                <p className="font-medium">
                  No work measured on a BOQ line and no labour put on one in
                  this period.
                </p>
                <p className="text-sm text-muted-foreground">
                  A line is coloured once the site's work is on its BOQ line and
                  the day's labour is put on it.{' '}
                  <Link
                    to={`/cost/budget?project=${projectId}#labour-to-lines`}
                    className="font-medium underline underline-offset-2"
                  >
                    Budget vs actual
                  </Link>
                </p>
              </div>
            ) : (
              <ul className="divide-y rounded-lg border">
                {v.lines.map((l) => (
                  <LineRow
                    key={l.line_id}
                    line={l}
                    projectId={projectId}
                    siteView={siteView}
                  />
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              {siteView
                ? 'Green: the labour put on the line is within what the BOQ allows for the work measured. Amber: up to 10% more. Red: more, or labour with no work measured.'
                : "Green: the work measured earned at least the labour it cost. Amber: within 10%. Red: less, or labour with no work measured. Earned is the work done × the line's labour rate in the BOQ."}
            </p>
          </DprSection>

          {v.materials && (
            <Callout tone="muted" icon={Package}>
              Materials: the work done in this period earned{' '}
              {formatRupees(v.materials.earned)} of material budget;{' '}
              {formatRupees(v.materials.bought)} of material was bought. Not
              coloured per line yet: what each line used comes with the material
              consumption register.
              {v.work_in_other_unit > 0 &&
                ` ${v.work_in_other_unit} work ${v.work_in_other_unit === 1 ? 'record is' : 'records are'} in another unit than its line and not added.`}
            </Callout>
          )}
        </>
      )}
    </div>
  );
}
