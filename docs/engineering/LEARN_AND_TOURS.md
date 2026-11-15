# Tours, walkthroughs and Learn Mesiri: the rules for every change

> Asked 15 Nov 2026 in session: "make sure the next updates also follow this". Applies to every dashboard change
> by a person or a Claude session: a new page, a changed page, a new feature, a page tour, a workflow, an outcome.
> Design and history: [learning-centre-plan.md](../plans/learning-centre-plan.md) (sections 9 to 11).

## Where things live

| What | File |
|---|---|
| Page tours (one per page, hand-written) and the app tour | `apps/dashboard/src/lib/tours.ts` |
| Workflows, workflow parts, outcomes ("What you get"), role paths | `apps/dashboard/src/lib/walkthroughs.ts` |
| The tour overlay (dim, light, Spark bubble) and page tours' runner | `apps/dashboard/src/components/tour.tsx` |
| The walkthrough engine (across pages, practice, take back, Done card) | `apps/dashboard/src/components/walkthrough.tsx` |
| The Learn page (`/learn`) | `apps/dashboard/src/pages/LearnPage.tsx` |
| What each page does on WhatsApp (examples and their tools) | `apps/dashboard/src/lib/module-map.ts` `whatsapp` |

One engine, one overlay, one definition. Never a second tour system, a page-specific popup tour, or a copy of a
step's words in another place.

## When you build or change a page

1. **Markers, never positions.** Point a step at `data-guide="<page>.<thing>"` on the element (or `guide="..."` on
   `Segmented` / `StatStrip`). Removing or renaming a marked element: fix its steps in the same change. The build
   fails otherwise (`vite.config.ts` `checkTourMarkers`), and that is the point: never silence it.
2. **WhatsApp examples.** A built page has `whatsapp` examples or a `whatsappNone` line in `module-map.ts`; each
   example names real assistant tools (`tests/agent_api/test_module_map_whatsapp.py`).
3. **A page tour** follows the recipe in the plan, section 5.4: 3 to 6 things, plain words, a Spark mood, keyed by the
   page path in `PAGE_TOURS`. If the page first asks for a project, give the tour `startWhen` (its content markers).
   It then appears on the Learn page, in its module card, and in every outcome that names `page-<path>`, by itself:
   add nothing else.
4. **Changed a page enough that people who finished its tour should see it again:** raise the tour's `version`.
5. **A list that a practice saves into:** give each row `data-record-id={record.id}`, so "There it is" can light up
   the exact row (`showNew: true` on that step).

## When you write a workflow (W1..W11)

- **Build it from parts** (`part: true`) and join them with `composed(...)`, so a role path or an outcome can use half
  of it (a site engineer gets W2's asking and delivery, not ordering). Never write the same step twice.
- **Steps go to built pages only** (`page:` must be a built page in `module-map.ts`; the build checks it). A workflow
  step whose element is not on screen (no data yet) is told in the middle of the screen, so write its text to make
  sense without the light: "Every evening each site gets its report", not "Click here".
- **Practice is real data** (decision D-L3). Every practice is one of these two, never neither:
  - **Save, then take back**: `try: { kind: 'whatsapp', say, tools, check }` (or `kind: 'here'` on the real button),
    then a "There it is" step (`showNew: true`), then a step with `takeBack` (the WhatsApp words and their undo
    `tools`, or the dashboard way). Only for records WhatsApp or the dashboard can take back (today: deliveries
    `undo_receipt`, usage `undo_usage`, transfers `undo_transfer`, expenses `undo_expense`, requests
    `cancel_material_request`, orders `cancel_order`). Check the tool exists in `agent_api/tools.py` `ALLOWED`.
  - **Look at the card, then Cancel**: `save: false`. For records that can't be taken back on WhatsApp (a site update,
    attendance, an advance, a payment). Nothing is saved.
- **A practice message must not create something new that stays behind** after the take-back: no supplier, worker,
  team or material name the company may not have ("10 bags cement came", not "... from Malabar"). Cancel practices
  may name people, since nothing is saved.
- **Every practice names its tools** (`tools: [...]`, and `tools` on `takeBack`); the WhatsApp test checks each is a
  real writing tool. Keep `say: '...', tools: [...]` on one line so the test reads it.
- **Never practice on a read-only account**: the engine skips practice there; don't work around it.

## When you add or change an outcome ("What you get")

- An outcome is **a title in the role's own words, one line on why it matters, and the walkthroughs it runs**
  (`OUTCOMES` in `walkthroughs.ts`). It writes no steps of its own. Name walkthroughs by id: a workflow or part
  (`site-update`), a page tour (`page-<path with - for />`, e.g. `page-planning-materials`), a module (`module-<key>`).
  The build fails on an id that doesn't exist.
- Title it by the value, not the screen: "Catch a cost overrun before the bill comes", not "BOQ page".
- The role path ("Everything ..., in order") is made from the role's outcomes by itself.
- Open: Project manager and Finance outcomes, and the owner's billing and month-end outcomes (SS-48).

## Before you push a change to any of this

1. `npx tsc -b --noEmit && npx oxlint src/ && npx vite build` in `apps/dashboard` (the build runs every check above).
2. The WhatsApp test, when `say` / `tools` changed:
   `PYTHONPATH=... python -m pytest tests/agent_api/test_module_map_whatsapp.py -q` in `apps/whatsapp-assistant`
   (PYTHONPATH as in the root `CLAUDE.md`).
3. Click it through in a browser against a stub API (Playwright, `require('playwright')`): start the walkthrough with
   `window.dispatchEvent(new CustomEvent('mesiri:walkthrough', { detail: '<id>' }))` and press Next to the end, at
   desktop and phone width, light and dark. In the stub, answer routes the page needs with their real shape and
   **every other route with an error (503)**, not `[]`: an empty list where a page expects an object crashes Today
   and Daily reports, which hides your change. Say in the report what was only checked against the stub.
