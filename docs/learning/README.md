# Mesiri Field Guides

Plain-language guides for the team (internal edition): how a construction company runs, each
Mesiri module, the problem it solves, how it looks and connects. Made to be read as PDFs and to be
loaded into NotebookLM. **Drafts:** construction details must be checked by someone with site
experience before they are used with customers.

Build: `node docs/learning/build.js [filter]` (Playwright, A4, page numbers) turns `src/*.html`
into `pdf/*.pdf`. Any screenshots in `img/` come from the demo company on a local copy, never production.

## The set (agreed 7 Nov 2026)

| # | Guide | Status |
|---|---|---|
| 00 | The big picture: how a construction company runs, where money leaks, one load of cement from order to payment, how every module connects | to do |
| 01 | Site | to do |
| 02 | Planning | to do |
| 03 | Materials | draft, 7 Nov |
| 04 | Procurement | to do |
| 05 | Labour | to do |
| 06 | Subcontract | to do |
| 07 | Cost control | to do |
| 08 | Finance | to do |
| 09 | Accounts | to do |
| 10 | Client billing | to do |
| 11 | Equipment | to do |
| 12 | Glossary | to do |

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
