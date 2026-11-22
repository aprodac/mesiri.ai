/**
 * Route cues (WEB-104, asked 22 Nov 2026: "in the sidebar a bit more color to routes, for visual cues"): each page's
 * icon sits on a small tile in its kind's colour, the phone app's category tiles (apps/mobile/src/theme.ts
 * `category`) carried to the dashboard, so the same kind of thing has the same colour on both. Money and planning
 * have no tile on the phone; they take teal and violet here. Pages that are about the app itself (Home, All pages,
 * Learn, Settings) stay neutral.
 *
 * `onDark` is the tile on the navy sidebar (a tinted ground, a light icon); `onPaper` the same kind on a light
 * ground (the page you are on, a paper pill).
 */
export type RouteCue = 'site' | 'problem' | 'material' | 'people' | 'money' | 'plan' | 'machine' | 'waiting' | 'neutral'

export const ROUTE_CUE_LOOK: Record<RouteCue, { onDark: string; onPaper: string }> = {
  site: { onDark: 'bg-[#1f6b52]/45 text-[#8fe0bb]', onPaper: 'bg-[#d9ede3] text-[#1f6b52]' },
  problem: { onDark: 'bg-[#c4472f]/40 text-[#ffb3a3]', onPaper: 'bg-[#f6dcd4] text-[#b2412b]' },
  material: { onDark: 'bg-[#d9a900]/30 text-[#ffd86a]', onPaper: 'bg-[#f8ecc4] text-[#7a5a00]' },
  people: { onDark: 'bg-[#3d64ad]/45 text-[#c3d3f2]', onPaper: 'bg-[#dfe6f3] text-[#1e3a6e]' },
  money: { onDark: 'bg-[#23617a]/55 text-[#93d6ee]', onPaper: 'bg-[#dcecf3] text-[#23617a]' },
  plan: { onDark: 'bg-[#4a3f88]/60 text-[#cdc5fa]', onPaper: 'bg-[#e6e2f2] text-[#4a3f88]' },
  machine: { onDark: 'bg-white/[0.10] text-[#d6d9e0]', onPaper: 'bg-[#ebe8e1] text-[#3a3d41]' },
  waiting: { onDark: 'bg-[#ffd23f]/25 text-[#ffe07a]', onPaper: 'bg-[#fff6d1] text-[#7a5a00]' },
  neutral: { onDark: 'bg-white/[0.07] text-[#9fb3da]', onPaper: 'bg-[#dfe6f3] text-[#1e3a6e]' },
}

/** First match wins: more specific prefixes first. */
const RULES: [string, RouteCue][] = [
  ['/site/approvals', 'waiting'],
  ['/site/quality', 'problem'],
  ['/site/safety', 'problem'],
  ['/site/snags', 'problem'],
  ['/issues', 'problem'],
  ['/today', 'site'],
  ['/reports', 'site'],
  ['/site-log', 'site'],
  ['/tasks', 'site'],
  ['/materials', 'material'],
  ['/procurement', 'material'],
  ['/cost/materials', 'material'],
  ['/finance/vendors', 'material'],
  ['/labour', 'people'],
  ['/team', 'people'],
  ['/subcontract', 'people'],
  ['/equipment', 'machine'],
  ['/accounts', 'money'],
  ['/billing', 'money'],
  ['/cost', 'money'],
  ['/finance', 'money'],
  ['/analytics', 'money'],
  ['/boq', 'plan'],
  ['/planning', 'plan'],
  ['/projects', 'plan'],
]

export function routeCue(url: string): RouteCue {
  const path = url.split('?')[0]
  for (const [prefix, cue] of RULES) if (path === prefix || path.startsWith(`${prefix}/`)) return cue
  return 'neutral'
}
