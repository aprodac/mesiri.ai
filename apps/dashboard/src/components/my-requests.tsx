import { useQuery } from '@tanstack/react-query'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fetchMyRequests, type MyRequest } from '@/lib/api'

// Request 230: what this person asked Mesiri for and where each one is.
const STAGE: Record<MyRequest['stage'], string> = {
  asked: 'Asked',
  building: 'Being built',
  live: 'Done',
  dropped: 'Dropped',
}

function day(value: string | null): string {
  const d = value ? new Date(value) : null
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

export function MyRequests() {
  const query = useQuery({ queryKey: ['my-requests'], queryFn: fetchMyRequests })
  if (query.isLoading) return <Skeleton className="h-16 w-full" />
  if (query.isError) return <p className="text-sm text-muted-foreground">Could not load your requests right now.</p>
  const items = query.data ?? []
  if (!items.length) return <p className="text-sm text-muted-foreground">Nothing open. Anything you ask Mesiri for will show up here.</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Request</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Date</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((r, i) => (
          <TableRow key={`${i}-${r.title}`}>
            <TableCell className="whitespace-normal">{r.title}</TableCell>
            <TableCell>{STAGE[r.stage]}</TableCell>
            <TableCell>{day(r.stage === 'live' ? r.live_at : r.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
