import type { AppScope } from './scope-types'

// The project or site picked in the top bar lives in the address (?project=, ?site=, lib/ScopeContext.tsx). Anything
// that sends a person to another page in the app keeps it with this, or the page they land on forgets it and asks for
// the project again: the sidebar and the walkthroughs (SS-52) both go through here.

/** Settings' pages keep their own addresses (UX-04): the picked project is not added to them. */
export const SETTINGS_PATHS = ['/settings', '/projects', '/team', '/company', '/whatsapp']

/** `url` with the picked project and site added (an address that already names a project keeps its own). */
export function urlWithScope(url: string, scope: AppScope): string {
  if (SETTINGS_PATHS.includes(url.split('?')[0])) return url
  if (scope.mode === 'portfolio') return url
  const [path, query = ''] = url.split('?')
  const params = new URLSearchParams(query)
  if (params.has('project')) return url
  params.set('project', scope.projectId)
  if (scope.mode === 'site') params.set('site', scope.siteId)
  return `${path}?${params.toString()}`
}
