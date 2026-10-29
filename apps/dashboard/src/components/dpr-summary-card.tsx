import { Sparkles } from 'lucide-react'

// BE-18: the AI-written summary of a confirmed DPR, made only from its
// confirmed facts. Shared by the site DPR page and the project DPR page.
// Rendered as plain text (React escapes it), like everything people typed.

export function DprSummaryCard({ summary }: { summary: string | null | undefined }) {
  if (!summary) return null
  return (
    <div className="flex gap-3 rounded-xl bg-ai-soft px-4 py-3.5">
      <Sparkles className="mt-0.5 size-4 shrink-0 text-ai" />
      <div className="flex flex-col gap-1">
        <span className="text-xs font-semibold text-ai">Summary</span>
        <p className="text-sm leading-relaxed">{summary}</p>
      </div>
    </div>
  )
}
