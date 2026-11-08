# Mesiri Field Guides

Plain-language guides for the team (internal edition): how a construction company runs, each
Mesiri module, the problem it solves, how it looks and connects. Made to be read as PDFs and to be
loaded into NotebookLM. **Drafts:** construction details must be checked by someone with site
experience before they are used with customers.

Build: `node docs/learning/build.js [filter]` (Playwright, A4, page numbers) turns `src/*.html`
into `pdf/*.pdf`. Any screenshots in `img/` come from the demo company on a local copy, never production.

## The set (agreed 7 Nov 2026: 10 guides)

| # | Guide | Status |
|---|---|---|
| 00 | The big picture: how a construction company runs and makes money, the life of a project, who's who, money flow, the biggest leaks, how every module connects | draft, 7 Nov |
| 00a | Roles: everyone in and around a construction company, what each wants from software, who sees and does what, and what Mesiri has | draft, 8 Nov |
| 01 | Site: daily reports, issues, quality, safety, equipment | to do |
| 02 | Planning & BOQ | to do |
| 03 | Materials | draft, 7 Nov |
| 03a | Material categories (deep dive: business, how Mesiri does it in code, what to build next) | draft, 8 Nov |
| 04 | Procurement | to do |
| 05 | Labour & subcontract | to do |
| 06 | Cost control | to do |
| 07 | Finance & accounts | to do |
| 08 | Client billing | to do |
| 09 | Glossary | to do |

## What every module guide contains, in this order (domain first, 7 Nov 2026)

Parts 1 to 7 are about the business, not about Mesiri; part 8 is the gap list to build from.

1. **How it works in a construction company**: the real process step by step, the paper documents, who does what.
2. **The problems** (the most space): where money leaks at each step, what owners complain about, and why software for it usually fails.
3. **What good control looks like**: the habits of well-run contractors and the numbers they watch.
4. **What a complete system needs**: the requirements checklist, each marked Must / Should / Nice, from industry practice and the major ERPs.
5. **Best UX** for this kind of software: do / don't.
6. **Where WhatsApp and voice fit**: which steps suit chat, which need a screen.
7. **How it connects** to the other modules (diagram).
8. **Mesiri today: the gap list**: the checklist from part 4, marked Have / Partly / Missing, with tracker IDs. This is the build list.
9. Key terms · questions customers ask · check yourself.

Sources: `apps/dashboard/src/lib/module-map.ts` (pages and status), the plans in `docs/plans/`,
the assistant's tools and SOP (`apps/whatsapp-assistant/src/agent_api/`), meeting notes.
