# Mesiri Field Guides

Plain-language guides for the team (internal edition): how a construction company runs, each
Mesiri module, the problem it solves, how it looks and connects. Made to be read as PDFs and to be
loaded into NotebookLM. **Drafts:** construction details must be checked by someone with site
experience before they are used with customers.

Build: `node docs/learning/build.js [filter]` (Playwright, A4, page numbers) turns `src/*.html`
into `pdf/*.pdf`. Screenshots in `img/` come from the demo company on a local copy, never production.

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

## What every module guide contains, in this order

1. **The problem without it** (the most space): what goes wrong, who feels it, what it costs, in the customer's words where we have them.
2. **The problems people hit while using it**, and how Mesiri's design avoids each.
3. Who uses it, and when.
4. One real site story, with numbers.
5. **The pages**: purpose, what must be on it, how it looks (screenshot if built, wireframe if planned), status.
6. The best UX for the module: do / don't.
7. **On WhatsApp**: what works today (only what really exists), what is planned.
8. How it connects: diagram of what feeds it and what it feeds.
9. Mesiri vs other software · customer questions · key terms · check yourself.

Sources: `apps/dashboard/src/lib/module-map.ts` (pages and status), the plans in `docs/plans/`,
the assistant's tools and SOP (`apps/whatsapp-assistant/src/agent_api/`), meeting notes.
