import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// BE-18: the AI-written summary of a confirmed DPR, made only from its
// confirmed facts. Shared by the site DPR page and the project DPR page.
// Rendered as plain text (React escapes it), like everything people typed.

export function DprSummaryCard({ summary }: { summary: string | null | undefined }) {
  if (!summary) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Summary</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed">{summary}</p>
      </CardContent>
    </Card>
  )
}
