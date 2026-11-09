import { api, fetchSiteIssuesApi, type SiteIssueItem } from '@/lib/api'

// DSH-10: every open issue, not just the latest 100 of all statuses: the server
// filters by status, and each status is read page by page (the API caps a page
// at 100) so the most severe ones are ranked from the whole list.
const ISSUE_PAGE = 100
export async function fetchAllOpenIssues(projectId: string | undefined): Promise<SiteIssueItem[]> {
  const all: SiteIssueItem[] = []
  for (const status of ['OPEN', 'ACKNOWLEDGED']) {
    for (let offset = 0; ; offset += ISSUE_PAGE) {
      const page = await fetchSiteIssuesApi({ projectId, status, limit: ISSUE_PAGE, offset })
      all.push(...page.items)
      if (page.items.length < ISSUE_PAGE || offset + ISSUE_PAGE >= page.total) break
    }
  }
  return all
}

/** GM-06: put someone on an issue, with the date they gave (either may be cleared). They are told on WhatsApp. */
export async function setIssueOwner(issueId: string, body: { assigned_user_id: string | null; due_on: string | null }): Promise<SiteIssueItem> {
  return (await api.put<SiteIssueItem>(`/progress/issues/${issueId}/owner`, body)).data
}

/** GM-06: remind the person on it, on WhatsApp (once a day). */
export async function remindIssueOwner(issueId: string): Promise<{ sent: boolean; message: string }> {
  return (await api.post<{ sent: boolean; message: string }>(`/progress/issues/${issueId}/remind`)).data
}
