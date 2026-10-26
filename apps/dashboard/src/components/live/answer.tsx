import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import type { ReviewItem, SiteDayDetail, SiteQuestion } from '@/lib/api'
import { keyValue, rowLines } from '@/lib/live-reading'
import { fetchInventory } from '@/lib/materials'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { CountTo, Ink } from './ink'

// The back of the Live report's sheet (WEB-37): when someone asks Mesiri a
// question on WhatsApp ("what stock is at Tower A?"), the report turns
// over and shows the answer from the same records Mesiri answered from:
// the site's stock, today's manpower, the work done, or the reply itself.

export interface AnswerTarget {
  name: string
  path: string
}

export function answerTitle(q: SiteQuestion, site: string, project: string): string {
  const where = q.whole_project ? project : site
  switch (q.kind) {
    case 'stock':
      return `Stock at ${where}`
    case 'manpower':
      return `Manpower at ${where}`
    case 'work':
      return `Work done at ${where}`
    case 'project':
      return project
    case 'report':
      return 'Daily report'
  }
}

export function questionChip(q: SiteQuestion, site: string): string {
  const what = { stock: 'Stock', manpower: 'Manpower', work: 'Work done', project: 'Project', report: 'Report' }[q.kind]
  return `${what} · ${site}`
}

/** One line of the answer, landing in turn: the number slams in. */
function AnswerRow({ name, value, sub, index, alert }: { name: string; value: string; sub?: string; index: number; alert?: boolean }) {
  const still = prefersReducedMotion()
  return (
    <li
      className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 border-b border-black/10 py-2.5 last:border-b-0 animate-in fade-in slide-in-from-bottom-1 fill-mode-both duration-500 motion-reduce:animate-none"
      style={{ animationDelay: `${700 + index * 160}ms` }}
    >
      <span className="min-w-0">
        <span className="block truncate text-[15px] font-semibold">{name}</span>
        {sub && <span className="block text-[12px] text-black/50">{sub}</span>}
      </span>
      <span
        className={cn('inline-block px-1 text-[20px] font-semibold tabular-nums', alert && 'text-red-700')}
        style={
          still
            ? undefined
            : {
                animation: `live-slam 700ms ${850 + index * 160}ms cubic-bezier(.2,.9,.3,1.2) both, live-marker 600ms ${1150 + index * 160}ms ease-out both`,
                backgroundImage: 'linear-gradient(transparent 52%, color-mix(in srgb, var(--primary) 28%, transparent) 52%)',
                backgroundRepeat: 'no-repeat',
              }
        }
      >
        {value}
      </span>
    </li>
  )
}

const qty = (n: string) => {
  const x = Number(n)
  return Number.isFinite(x) ? String(Math.round(x * 100) / 100) : n
}

export function AnswerSheet({
  question,
  title,
  projectId,
  siteId,
  labour,
  workRows,
  stockOn,
  target,
  onOpen,
  onBack,
}: {
  question: SiteQuestion
  title: string
  projectId: string | undefined
  siteId: string
  labour: SiteDayDetail['report']['labour'] | null
  workRows: ReviewItem[]
  /** Materials is switched on (the stock comes from it). */
  stockOn: boolean
  target: AnswerTarget | null
  onOpen: (el: HTMLElement) => void
  onBack: () => void
}) {
  const stock = useQuery({
    queryKey: ['live-answer-stock', projectId, question.whole_project ? null : siteId],
    queryFn: () => fetchInventory({ project_id: projectId, site_id: question.whole_project ? undefined : siteId }),
    enabled: question.kind === 'stock' && stockOn && !!projectId,
    staleTime: 10_000,
  })
  const asked = (question.translated_text || question.text || '').trim()
  const at = question.received_at
    ? new Date(question.received_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : ''

  let body: ReactNode = null
  if (question.kind === 'stock' && stock.data && stock.data.length > 0) {
    body = (
      <ul className="m-0 list-none p-0">
        {stock.data.slice(0, 8).map((m, i) => (
          <AnswerRow
            key={`${m.site_id}:${m.material_id}`}
            index={i}
            name={m.material_name}
            sub={`in ${qty(m.total_received)} · used ${qty(m.total_used)}`}
            value={`${qty(m.current_stock)} ${m.unit}`}
            alert={m.stock_state !== 'AVAILABLE'}
          />
        ))}
      </ul>
    )
  } else if (question.kind === 'manpower' && labour) {
    body = (
      <div className="grid gap-3">
        <div className="flex items-baseline gap-3">
          <span
            className="inline-block text-[64px] font-semibold leading-none tabular-nums"
            style={prefersReducedMotion() ? undefined : { animation: 'live-slam 800ms 700ms cubic-bezier(.2,.9,.3,1.2) both' }}
          >
            <CountTo value={labour.headcount} />
          </span>
          <span className="text-[15px] text-black/60">{labour.headcount === 1 ? 'worker' : 'workers'} on site today</span>
        </div>
        {labour.trades.length > 0 && (
          <ul className="m-0 list-none p-0">
            {labour.trades.map((t, i) => (
              <AnswerRow key={t.trade} index={i} name={t.trade} value={String(t.headcount)} />
            ))}
          </ul>
        )}
      </div>
    )
  } else if (question.kind === 'work' && workRows.length > 0) {
    body = (
      <ul className="m-0 list-none p-0">
        {workRows.slice(0, 8).map((item, i) => (
          <AnswerRow key={item.id} index={i} name={rowLines(item).main} sub={rowLines(item).sub ?? undefined} value={keyValue(item) ?? '✓'} />
        ))}
      </ul>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-4">
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-black/50">
          Asked{at ? ` at ${at}` : ''}
          {question.sender_name ? ` · ${question.sender_name}` : ''}
        </span>
        <span className="rotate-[-4deg] border-2 border-primary px-2 py-0.5 font-brand text-[11px] tracking-[0.08em] text-primary">
          ANSWERED
        </span>
      </div>
      {asked && <p className="m-0 mt-2 text-[15px] italic text-black/60">“{asked}”</p>}
      <h3 className="m-0 mt-4 text-[26px] font-semibold leading-tight tracking-[-0.01em]">
        <Ink text={title} writing={!prefersReducedMotion()} delay={350} />
      </h3>
      <div className="mt-4 h-[3px] bg-primary" />
      <div className="mt-4 flex-1">
        {body ?? (
          // Nothing to tabulate (a project question, or no records): Mesiri's own answer.
          <p className="m-0 whitespace-pre-line text-[15px] leading-relaxed">
            <Ink text={question.reply?.trim() || 'Mesiri answered on WhatsApp.'} writing={!prefersReducedMotion()} delay={700} />
          </p>
        )}
      </div>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-black/10 pt-3">
        <button type="button" onClick={onBack} className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.06em] text-black/60 hover:text-black">
          <ArrowLeft className="size-3.5" /> Back to the report
        </button>
        {target && (
          <button
            type="button"
            onClick={(e) => onOpen(e.currentTarget)}
            className="flex items-center gap-2 bg-[#1a1d21] px-3.5 py-2 text-[13px] font-medium text-white hover:bg-black"
          >
            Open {target.name} <ArrowRight className="size-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
