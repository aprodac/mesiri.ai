# Answer Composer — phase plan (WhatsApp rich replies)

> **Status:** Phase 2 plan, **awaiting approval**. Nothing here is implemented.
> **Design page:** [Mesiri Answer Composer](https://claude.ai/artifact/HjkNXhWS35YTyDyWunSt1S)
> **Tracker:** WA-14 … WA-18 and the open decision "Answer composer in V1" in
> [V1_TRACKER.md](V1_TRACKER.md).
> **Written:** 14 Oct 2026.

## 1. Objective

Let the WhatsApp assistant pick the clearest way to send each answer (a sentence, a short
list, a card image, a PDF, or buttons for the next step) from the shape of the data,
instead of every reply format being fixed in code. The user should never have to say
"send it as a PDF".

## 2. Why (findings from Phase 1)

| Finding | Where |
| --- | --- |
| The LLM only classifies and extracts JSON. It never sees a lookup's result and never writes a reply | `platform/ai/src/mesiri_ai/ports/generation.py` |
| The planner is a dictionary lookup from event type to workflow | `apps/whatsapp-assistant/src/planner/planner.py` |
| Reply format is fixed per code path; buttons are "only ever set for a workflow confirmation prompt" | `channel/replies.py` (`ReplySpec`) |
| Lookups cut off at 5 lines plus "... and N more" | e.g. `workflows/expense_query/nodes.py` |
| PDF tables already exist for 6 lookups, but the extractor is told to set `output_format="pdf"` **only** when the user explicitly asks | `runtime/inbound_journey/seeding.py` (`_build_query_pdf`), `platform/ai/.../gemini/adapter.py` |
| Every new photo gets the same 4-row purpose menu, whatever vision saw | `channel/replies.py` (`IMAGE_PURPOSE_ROWS`) |
| "Who reported today?" is answerable only by the 3 pm automation, not in chat | `runtime/reporting_compliance_query.py` |
| An HTML→PNG renderer with a warm Chromium page pool already exists (receipt cards) | `channel/receipt/render.py` |

## 3. V1 alignment

V1 is one feature, the automatic DPR. Companies get `dpr`, `labour` and `materials`
switched on by default (`V1_MODULES` in `backend/src/mesiri/domains/organizations/settings.py`).
Measured against that:

- **In V1.** The rich-reply foundation, because the V1 evening messages need it.
  - WA-05: the evening DPR sent to the engineer to confirm, with "Confirm all" / "Fix something".
  - WA-04: the evening gap-check.
  - WA-02: one summary reply for forwarded batches.

  A card image plus buttons in one message is the natural shape for all three. Building
  the foundation once, before those items, stops each of them hand-rolling its own format.
- **In V1 if approved.** Rule-based formats (no AI) for the lookups V1 companies can
  reach: material stock, labour, activity, project detail. Also "who reported today?"
  asked in chat, which is DPR visibility for owners and PMs.
- **Later.**
  - The AI composer itself (shadow, then live).
  - The confident photo guess.
  - Expense and finance charts: finance is not a V1 module, so the expense example on the
    design page is out of V1.

Cross-item dependencies:

| Item | Relationship |
| --- | --- |
| **BE-36** (in progress, plan awaiting approval) | Autoescape user text in the receipt and DPR renderers. **WA-14 depends on it**: the card renderer reuses that Chromium setup and must not inherit the raw-HTML / SSRF hole |
| **WA-11** (done) | `runtime/reply_language.py` supplies the caption language. Reused, not rebuilt |
| **WA-12** (done) | Templates outside the 24 h window. The composer only runs for in-session replies. Template messages stay fixed |
| **BE-25** (todo) | AI cost tracking. WA-17 adds one AI call per lookup and must log it there, or log locally until BE-25 lands |
| **BE-06 / WA-07** (done) | Module switches. Buttons offered by a payload come from `workflows/registry.py` filtered by enabled modules and role, so a switched-off feature is never offered |

## 4. Scope

**In:** read-only answers and the outbound message shapes (image, document, image-header
buttons, link button) that the V1 evening messages reuse.

**Out (unchanged):**
- How things are recorded: save-first drafts (WA-01), UNDO, confirmations.
- The extraction and planner prompts. An explicit "send as PDF" keeps winning.
- Templates.
- Database, migrations, backend API, dashboard.

## 5. Phases

Each phase follows CLAUDE.md on its own: test, commit, push, update docs and tracker,
report, **wait for approval** before the next.

### Phase A — Rich reply foundation (WA-14) · M · Must · depends on BE-36

Outbound shapes and a card renderer. No change to what any existing reply says.

| Area | Work |
| --- | --- |
| `channel/replies.py` | `ReplySpec` gains optional `image: bytes`, `document: (bytes, filename)`, `cta: (label, url)`. It stays assistant-local, not a shared contract |
| `channel/whatsapp/outbound.py` | Button message with an **image header** (one message: image + up to 3 buttons); `cta_url` link button. Reuses the existing upload-then-send media flow |
| `runtime/reply_dispatch.py` | Sends the parts in order. Image + buttons are merged into one message. At most 2 messages per reply. Falls back to text if a send fails |
| `channel/receipt/render.py` → new `channel/cards/snapshot.py` | Move the page pool into a shared HTML-snapshot helper. Receipt output must be byte-for-byte unchanged (tested). Autoescaping per BE-36 |
| `channel/cards/templates/` | Two templates: **table card** (title, columns, rows, highlighted rows, footer note) and **roster card** (people × status). 680 px wide, ≤ 12 rows, large type for small phones |

**Done when:** the new shapes are tested against the fake sender, and one live send of
each shape to a test number has been made and screenshotted. Receipts are unchanged.

### Phase B — Data, not sentences, for V1 lookups (WA-16) · M · Must if approved · depends on WA-14

| Area | Work |
| --- | --- |
| new `presentation/payload.py` | `AnswerPayload`: kind, title, facts, table (columns, rows, flags), optional series, actions (built from the registry + role + enabled modules), `as_of` |
| new `presentation/policy.py` | Pure rules: data shape → allowed formats + default (see the design page's table). Enforces Meta's limits: 3 reply buttons, 10 list rows, 24-character row titles, 20-character button labels, 1,024-character body |
| 4 query nodes | `material_inventory_query`, `labour_query`, `activity_query`, `project_detail_query` emit a payload **next to** today's `pending_prompt`, which stays as the fallback |
| `runtime/inbound_journey/process.py` | For those workflows, when `PRESENTATION_COMPOSER` is `policy` or higher: render via policy → renderers → dispatch, and on any error send `pending_prompt` |
| reuse | `_build_query_pdf` / `render_table_pdf` for the "Full list (PDF)" button. No second PDF path |

**Labour isolation.** `labour_query` is read-only. The only change is that its reply node
also returns a payload built from the `labour_results` already seeded today. No Labour,
Attendance, Payroll or Workforce service, table or write path changes.

**Done when:** a stock question with 9+ items gets a card, a caption that works without
the image, and buttons. Short answers stay text. With the flag off, every existing reply
test passes unchanged.

### Phase B2 — "Who reported today?" in chat (WA-15) · S · decision · depends on WA-16

- A read-only query workflow reusing `ReportingComplianceQueryService`, the same
  definition of "reported" the 3 pm automation and `site_days` use.
- The reply is policy-chosen: text roster for a few engineers, roster card for many. A
  "Remind them" button uses the existing notification path.
- Role-gated to owner, PM and admin.
- Adds one registry entry and one extraction semantic type. Needs Alan's approval because
  it touches the shared extraction prompt.

### Phase C — Consumers in the V1 evening flow (notes on WA-05, WA-04, WA-02)

No new tracker rows. When those items are built, they use WA-14:
- **WA-05:** today's site DPR as a table card (work done, labour, materials, issues),
  plus "Confirm all" / "Fix something" buttons in one message.
- **WA-04:** a list of missing sections plus buttons to answer each.
- **WA-02:** one summary card for a forwarded batch.

### Phase D — AI composer (WA-17) · M · Later · depends on WA-16 (BE-25 for cost logging)

| Area | Work |
| --- | --- |
| new `presentation/composer.py` | One `JsonGenerationProvider` call through the existing resolver. Input: user text, payload **shape** (not values), allowed formats, role, language. Output: `PresentationPlan` (parts, placeholder-only text, chosen actions, reason). 1.5 s budget; on timeout, the policy default |
| new `presentation/validator.py` | Rejects a plan with any digit outside a `{placeholder}`, unknown actions, formats outside the allowed set, or over-limit text |
| rollout | `PRESENTATION_COMPOSER=shadow`: the plan is built and logged, and the default is sent. Eval set of about 40 real questions (English, Hinglish, Malayalam) in `tests/eval/`. Turn `live` on per environment only when it matches or beats the default |

### Phase E — Confident photo guess (WA-18) · S–M · Later · depends on WA-14

- When vision is confident, reply "Looks like a delivery challan from X: 50 bags cement",
  with buttons **Record delivery / It's an expense / Something else**.
- Below the threshold, keep today's 4-row menu.
- Touches the interaction leg (`interactions/image_purpose.py`, `pending_media.py`), so it
  goes last.

## 6. Plan sections required by CLAUDE.md

| Section | Answer |
| --- | --- |
| Business value | Fewer follow-up messages ("send the full list"); owners see stock and reporting status at a glance; the V1 evening confirmation reads like a report, not a wall of text |
| Files expected to change | Phases A–E above. All inside `apps/whatsapp-assistant/src/` except the extraction prompt in WA-15 |
| Backend work | None in `backend/` (reads existing services in-process, as today) |
| Frontend work | None |
| Database work | None. No migrations |
| API work | None. WhatsApp Cloud API: new outbound payload shapes only (image-header button, cta_url) |
| Risks | See the table below |
| Testing strategy | Unit: policy, validator, payload builders, card HTML (pure). Renderer behind the Playwright marker, like receipts. Regression: full assistant suite (~9 min, PYTHONPATH per CLAUDE.md) with the flag off and on. Receipt byte-equality test. Live test-number send per new shape, reported as a gap if it can't be done |
| Rollback | Env flag `PRESENTATION_COMPOSER` = `off` / `policy` / `shadow` / `live`. `off` is exactly today's behaviour. No stored data, so reverting commits is safe |
| Labour isolation | Read-only payload emitter on `labour_query` only. Nothing else in Labour, Attendance, Payroll or Workforce |
| Success criteria | No reply number missing from its payload (validator count = 0 accepted). p95 lookup reply ≤ today + 1.2 s. Card + buttons render on Android and iOS WhatsApp. Fewer "full list / PDF" follow-ups after a lookup |

### Risks

| Risk | Mitigation |
| --- | --- |
| A wrong number in a labour or material answer | Phases A–C have no AI in the reply at all. Phase D allows placeholders only, plus the digit validator |
| Card renderer inherits the raw-HTML / SSRF issue | Hard dependency on BE-36. Card templates autoescape all values |
| Latency | Warm page pool, typing indicator already sent, 1.5 s composer budget, text fallback |
| Images on slow networks | The caption always carries the answer on its own |
| Message spam | At most 2 messages per reply. PDF offered as a button unless asked for or 30+ rows |
| Shared code changes (`ReplySpec`, receipt renderer refactor, extraction prompt for WA-15) | Flagged for approval before Phase A and B2 |
| Meta behaviour differs from the docs (image header, cta_url) | One live send per shape before the phase is reported done |
