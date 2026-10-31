> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Composite Request Plan Layer — Design Doc

**Status:** Phases 1–4 done (2026-07-30), including `EDIT` (drop a step and its dependents, re-preview). Decomposition, entity-linking, the generic executor, wiring into `process_inbound_message`, the member-create swap, and the §8 preview with Yes/No/Edit are all live. **The Paraclette/Starship message works end to end**, gated behind its own Yes/No/Edit before anything executes. Remaining: Phase 5 (migrate the other entity types), Phase 6 (whole-plan permission pre-check, separate security review — **now confirmed a real gap**: `plan_executor.py` has no role check at all, so a disallowed step is caught only by backend-layer defense-in-depth, not refused upfront the way the single-message path does), the known §9 gap (a segment missing a required field is silently dropped, not yet surfaced in the preview), and the fact that the material/unit/project/site gates from the single-message path never re-run per decomposed segment.
**Owner:** Ilan Usman
**Started:** 2026-07-30
**Last updated:** 2026-07-30
**Linear:** _(epic to be created — see §11)_

> **Resuming in a new session?** Read §11 first — it says what is built and
> what is next. Then §4 (how this layer and the entity-resolution layer
> interlock — they share one store and one executor, and splitting them would
> produce two competing orchestrators), §9 (decomposition, the remaining
> piece, now settled by real trace evidence) and §3 (the binding principles).

> **Purpose of this document.** Durable memory for this layer. If a future
> session — human or AI — loses all conversational context, this file alone
> should explain what exists, what is being built, what remains, why each
> decision was made, and what to do next.

---

## 1. What this layer is

**One WhatsApp message may state several things that must happen in a
particular order, and Mesiri must do all of them.**

The message that motivates it, verbatim from the field:

> create a project named Paraclette and then create a site named Tower B,
> add Hysamm for it with WhatsApp number 9847656072, make him the project
> manager, and create an activity that slab work is started

That is five intents with a real dependency structure:

```
1. create project "Paraclette"
2. create site "Tower B"              needs (1)
3. create user "Hysamm" +919847656072
4. make Hysamm PM of Paraclette       needs (1) and (3)
5. activity "slab work started"       needs (1) and (2)
```

Today this message produces **one** workflow — whichever single intent the
extractor happened to pick — and silently drops the rest.

**What this layer is not.** It is not a new LangGraph graph, and it must
never become one. See ADR-C1.

---

## 2. What already exists (verified 2026-07-30)

This layer is roughly 70% built. Naming it accurately matters, because the
temptation is to rebuild rather than extend.

| Piece | Where | State |
|---|---|---|
| Multi-segment canonicalization | [`canonicalization/builder.py:478`](../../apps/whatsapp-assistant/src/canonicalization/builder.py) `build_canonical_events` | Returns a **list**. Only ever produces >1 for the one deterministic material→activity case (`_build_linked_activity_segment`). Its own docstring states free-text splitting is not attempted. |
| Segment queue | [`workflows/batch_store.py`](../../apps/whatsapp-assistant/src/workflows/batch_store.py) `PendingBatchStore` | Redis, per user, 30-min TTL, pop-one-at-a-time, running outcome log. **Flat FIFO — no dependency notion.** |
| Segment runner | [`workflows/batch.py`](../../apps/whatsapp-assistant/src/workflows/batch.py) | `start_segment`, `(2 of 3)` prefixing, per-segment outcome lines, closing summary. |
| Batch kickoff | [`runtime/inbound_journey/process.py:898`](../../apps/whatsapp-assistant/src/runtime/inbound_journey/process.py) | Primary segment starts normally; remainder queued. |
| Single-source-of-truth registry | [`workflows/registry.py:73`](../../apps/whatsapp-assistant/src/workflows/registry.py) `WorkflowDefinition` | Explicitly designed so "adding a workflow means editing one table rather than hunting down per-key sets scattered across modules." This is where the dependency graph belongs. |
| Single-active invariant | [`workflows/runtime.py:281`](../../apps/whatsapp-assistant/src/workflows/runtime.py) | At most one `AWAITING_CONFIRMATION` instance per user, enforced by a partial unique index. **Non-negotiable — §7.5 explains how a plan lives inside it.** |

What is missing is exactly three things: decomposition (§9), ordering (§7.1),
and late binding (§7.2).

### 2.1 The blocking structural fact

`CanonicalEventV2` carries `organization_id` / `project_id` / `site_id`
resolved by `context/resolver.py` **before any workflow runs**.
[`site_create/nodes.py:36`](../../apps/whatsapp-assistant/src/workflows/site_create/nodes.py) reads
`state["project_id"]` and gives up if empty.

For "create Paraclette, then Tower B under it," Paraclette does not exist at
context-resolution time. Step 2 is therefore **structurally guaranteed to
fail today** — not a bug in `site_create`, a layering fact. §7.2 is the
answer.

---

## 3. Binding principles

- **P1 — No new graphs.** Leaf workflows are correct and stay untouched. A
  composite request is orchestration *above* them, never a new graph that
  re-implements their domain rules.
- **P2 — Order is derived, never authored.** Nowhere in the codebase will
  the sentence "site after project" be written. It falls out of a
  topological sort over registry declarations.
- **P3 — Nothing is written before the user has seen the whole plan.**
  Decomposition is an LLM judgement; the plan preview is the safety net.
- **P4 — Partial failure is reported honestly, never papered over.**
  Inherits [`batch.py`](../../apps/whatsapp-assistant/src/workflows/batch.py)'s
  existing stance: every segment gets exactly one outcome line, success or
  failure alike.
- **P5 — One plan, one executor.** See §4. This is the principle that keeps
  this layer and the entity-resolution layer from becoming two systems.
- **P6 — The single-active invariant is not relaxed.** The plan occupies the
  one slot; its steps do not each take one.

---

## 4. Relationship to the Entity Resolution & Continuation layer

> **Reconciled against [`ENTITY_RESOLUTION_PLAN.md`](ENTITY_RESOLUTION_PLAN.md)
> (his doc, dated 2026-07-30). One field-naming match, one real structural
> gap found — §4.4. Do not start either layer's Phase 1 until §4.4 is
> resolved.**

That doc covers the *other* half of the same problem: a **single** intent
that discovers mid-flight that a prerequisite entity does not exist ("add
Hysam as PM" when no user Hysam exists →
[`projects/handlers.py:173`](../../backend/src/mesiri/application/projects/handlers.py)
hard-rejects, per his §1).

The two layers split exactly as expected:

| | Entity Resolution layer (his) | **This layer** |
|---|---|---|
| Trigger | One intent, prerequisite missing at runtime | One message, several intents stated up front |
| Discovers dependencies | During execution | Before execution |
| Motivating message | ഹൈസം / "add Hysam as PM" (his §1) | the Paraclette message (§1, this doc) |

**Not alternatives, no scope overlap.** The Paraclette message needs both —
the moment "Hysamm" is misspelled, a *planned* step hits a *missing entity*.

### 4.1 The shared registry field — already agreed, no naming fight

His §3.2 independently proposed `provides` / `requires` on
`WorkflowDefinition` — the exact names guessed in the first draft of this
section. **Adopted verbatim, no change needed:**

```python
provides: frozenset[EntityType]   # CREATE_USER -> {USER}
requires: frozenset[EntityType]   # ADD_PROJECT_MEMBER -> {USER, PROJECT}
```

- His layer reads it **backwards**: "a USER is missing — which workflow
  provides one?" (his §3.2, `workflow_that_provides`)
- This layer reads it **forwards**: "these five steps — what order?" (§7.1)

One table, two readers, zero disagreement.

### 4.2 `EntityType`'s location — his open question #3, answered here

His §7.3 asks whether `EntityType` belongs in `shared/contracts`. His own
precedent answers it: `WorkflowCategory` is deliberately kept out of
contracts as registry-local metadata. `EntityType` should live the same
place — proposed: `workflows/registry.py` itself, or a new
`workflows/entities.py` if the enum grows large enough to want its own
module. Not `shared/contracts` unless a backend resolver ever keys off it
directly (his own caveat).

### 4.3 `allowed_roles` — two different uses, not a conflict

His ADR-E5 filters entity-creation *offers* by `allowed_roles`: don't offer
CREATE_USER to a SITE_ENGINEER who triggered a missing-USER lookup. That is
the field's **existing, documented purpose** — discovery/offer filtering,
not enforcement (`registry.py`'s own comment on the field). His use is
consistent with what the field already is. No change needed for his layer.

This layer's §7.3 wants something stronger: a **hard, load-bearing,
whole-plan** permission check before a multi-step preview is shown, so a
plan doesn't stop halfway through something already approved. That is a
genuine promotion of the field from advisory to enforcing, and stays
sequestered in this doc's own Phase 5 (separately reviewed), not his Phase 2.
**These are two different consumers of the same field, at two different
strictness levels — call this out explicitly wherever both docs are read
together, since the field name is identical and the difference is easy to
miss.**

### 4.4 The one real gap — his continuation is depth-1, this layer needs N

His mechanism (§3.3, ADR-E3) generalizes `PendingReportStore`: hold **one**
paused `CanonicalEventV2` plus which single entity is missing, run the
provider workflow, substitute the id, resume. ADR-E3 explicitly scopes this
to **depth 1** and calls a stack out-of-scope for V1 — a reasonable limit
for "one intent, one missing prerequisite."

This layer needs an **ordered list** of N steps (§6, `Plan`/`PlanStep`),
because the Paraclette message has five, with real dependencies between them.
A depth-1 pause is a plan of size 1; a plan is not reducible to a depth-1
pause. If his layer is built on `PendingReportStore` and this layer is built
on a separate `PlanStore`, we get exactly the two-orchestrator outcome both
docs are trying to avoid — two Redis shapes, two resume paths, and an
undefined answer for what happens when a *planned* step (this layer) hits a
*missing entity* (his layer) partway through a five-step plan.

**Proposed resolution, for him to confirm before either Phase 1 starts:**
his Phase 1 "one generic continuation" is implemented as inserting one step
into a `Plan` of size 1 (§6's `Plan`/`PlanStep`/`PlanStore`), not as a
generalized `PendingReportStore`. Concretely: `PendingReportStore`'s "hold
event + missing entity + resume" becomes "hold a one-step `Plan`; a missing
entity inserts a `PlanStep` before it; resume is `PlanStore`'s existing
pop-and-advance." ADR-E3's depth-1 limit is then an **operating constraint
on what the entity-resolution layer is allowed to insert** (still true, still
enforced), not a property baked into the storage shape. His Phase 2 (USER)
and Phase 3 (MATERIAL) prove the mechanism against a plan of size 1 — this
layer's Phase 4 proves it against a plan of size 5. Same store, same resume
path, one written down in Phase 1 instead of twice.

This is the one item that must be settled, in writing, in his doc, before
either side writes code — everything else in this section is already
compatible as-is.

### 4.5 What this doc still defers to his

- The `EntityType` enum's members and the fuzzy-match/`Ambiguous` mechanics
  (his §3.1, `match_worker` prior art).
- Cross-script matching policy (his open question #2 — Malayalam original vs.
  transliteration).
- The seven `resume_pending_report_with_*` collapse (his §5, Phase 4).
- ADR-E2 (backend resolvers stay as defence-in-depth) and ADR-E4 (offers are
  always tappable, never auto-create) — both apply unchanged to any step this
  layer inserts too.

This doc owns: decomposition (§9), topological ordering (§7.1), symbolic
references and just-in-time canonicalization (§7.2, ADR-C2), the plan
preview (§8), plan-wide permission gating (§7.3, Phase 5), and
dependency-aware cancellation (§7.4).

---

## 5. Architecture Decision Records

**ADR-C1 — No composite graphs.**
*Rejected:* authoring a LangGraph graph per combination (`project+site`,
`project+site+member`, `site+member`, `project+member+activity`, …).
*Why:* combinatorial in the number of workflows, and every combo graph
re-implements domain rules that already live in the leaf workflows. Ordering
is not a property of *pairs of workflows*; it is a property of what each
workflow **produces and consumes**. Declare that once per workflow (~28
declarations) and the order is derived (P2).

**ADR-C2 — Steps are canonicalized just-in-time, not up front.**
*Rejected:* extending `CanonicalEventV2` with nullable reference fields so a
whole plan can be canonicalized in one pass.
*Why:* §2.1. `project_id` cannot be resolved for step 2 before step 1 runs.
Building each step's `CanonicalEventV2` immediately before that step
executes means `site_create/nodes.py` sees a real `project_id` and **needs
zero changes**. `CanonicalEventV2` is unchanged. Every leaf workflow is
unchanged. This is the cheapest possible seam.

**ADR-C3 — One confirmation for the whole plan.**
*Rejected:* the current per-segment behaviour (each segment gets its own
YES).
*Why:* five taps, and at tap #1 the user cannot see what they are agreeing
to. A plan preview is also the only structural defence against a bad LLM
decomposition (P3). Per-step prompts survive only for steps needing genuine
disambiguation.

**ADR-C4 — Fail forward with dependency-aware cancellation; no rollback.**
*Rejected:* two-phase commit / compensating transactions across modules.
*Why:* the writes span independent domain modules with their own ledgers
(ADR-D2/P3 in the Daily Reporting plan forbids cross-module writes anyway).
Instead: a failed step **cancels its dependents without attempting them**
(they would fail, or worse, attach to the wrong project) while independent
steps still run. See §7.4.

**ADR-C5 — Role gates are checked for the entire plan before the preview.**
*Why:* the gates today are per-`workflow_key` early returns in
[`process.py:836`](../../apps/whatsapp-assistant/src/runtime/inbound_journey/process.py).
Under a plan, hitting one mid-execution means stopping halfway through
something the user already approved. See §7.3 — and note this is a real
change to a governance surface, not a refactor.

---

## 6. Contracts

New package `apps/whatsapp-assistant/src/planning/`.

```python
# planning/plan.py

@dataclass(frozen=True, slots=True)
class StepRef:
    """A value not known until an earlier step has executed."""
    step_id: str          # "s1"
    output_key: str       # "project_id"

@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    workflow_key: WorkflowKey
    #: Extracted fields. Values may be literals OR StepRef.
    fields: dict[str, object | StepRef]
    #: Derived from the registry, not authored per step.
    depends_on: tuple[str, ...]
    status: StepStatus    # PENDING | RUNNING | DONE | FAILED | CANCELLED
    #: Populated on DONE. Feeds every StepRef pointing at this step.
    outputs: dict[str, str]

@dataclass(frozen=True, slots=True)
class Plan:
    plan_id: str
    correlation_id: str
    steps: tuple[PlanStep, ...]     # already topologically ordered
    origin: PlanOrigin              # DECOMPOSITION | RESOLUTION | MIXED
```

`PlanOrigin` exists so the two producers (§4.2) are distinguishable in
traces without being distinguishable in machinery.

**Registry additions** (shared — see §4.1):

```
PROJECT_CREATE      provides={PROJECT}     requires={}
SITE_CREATE         provides={SITE}        requires={PROJECT}
CREATE_USER         provides={USER}        requires={}
ADD_PROJECT_MEMBER  provides={MEMBERSHIP}  requires={PROJECT, USER}
SITE_UPDATE         provides={ACTIVITY}    requires={PROJECT, SITE}
```

`PendingBatchStore` generalizes into `PlanStore` (same Redis key shape, same
TTL reasoning, same pop-once discipline). `batch.py`'s formatting functions
largely survive.

---

## 7. Execution semantics

### 7.1 Ordering
Topological sort over `depends_on`, derived from registry
`provides`/`requires`. A cycle or an unsatisfiable requirement **refuses the
whole plan and asks** rather than executing a prefix of it.

### 7.2 Binding — the hard part
Each `StepRef` resolves in this order:

1. **A prior step in this plan provides it** → bind to that step's output.
2. **It resolves by name against the database** → bind the existing entity.
   *This is what makes "add Hysamm to Paraclette" work when Paraclette
   already exists.*
3. **Neither** → hand to the entity-resolution layer (§4.3), which either
   offers to create it (inserting a step, §4.2) or asks.

Existing-vs-new is therefore **one code path, not two**.

`provides` must carry not just *which* entity a workflow creates but the
**id that flows into dependent steps**. This is the part that silently
breaks if left implicit; `PlanStep.outputs` is where it is made explicit and
typed.

### 7.3 Permissions
Every step's role requirement is checked **before the preview is rendered**
(ADR-C5). A plan containing one disallowed step is refused as a whole, naming
the offending step. This requires the role gates currently living as literals
in `process.py` to become registry data — noting that
[`registry.py`](../../apps/whatsapp-assistant/src/workflows/registry.py)'s
`allowed_roles` field today is *explicitly documented as discovery metadata
and not an enforcement gate*. **Promoting it to load-bearing is a deliberate
change to a security surface and needs its own review**, not a quiet
refactor. Until that review happens, Phase 3 keeps the `process.py` gates and
runs them in a loop over the plan's steps.

### 7.4 Failure
A failed step marks its transitive dependents `CANCELLED` without attempting
them. Independent steps still run. In the Paraclette example, if step 1
fails: steps 2/4/5 cancel, step 3 (create user — no dependency on 1) still
runs. The user gets one honest line per step, via
`summarize_batch_outcome`, which already does exactly this.

### 7.5 The single-active invariant
One `WorkflowInstance` in `AWAITING_CONFIRMATION` holds the **plan**. Its
steps start and complete inside that slot. The partial unique index in
[`runtime.py:281`](../../apps/whatsapp-assistant/src/workflows/runtime.py) is
untouched (P6).

---

## 8. Confirmation UX

```
I'll do 5 things:
1. Create project Paraclette
2. Create site Tower B under it
3. Add Hysamm (+91 98476 56072) as a new user
4. Make Hysamm project manager of Paraclette
5. Log activity "slab work started" at Tower B

YES to do all  ·  EDIT  ·  NO
```

One YES executes the whole plan — including, in this example, creating a
user and granting them project-manager rights, which is the largest blast
radius in the list. That is the deliberate trade for P3's preview.

**Preview built 2026-07-30**, matching the mockup above closely but not
exactly — `planning/preview.py`'s `render_plan_preview` renders one line per
step (`describe_step`, bespoke phrasing for the five workflow keys the
entity-linking rule connects, a `registry.title`-based fallback for
anything else), `channel/replies.py`'s `render_plan_preview_reply` attaches
Yes/No/Edit (`PLAN_CONFIRM_YES_ROW_ID`/`PLAN_CONFIRM_NO_ROW_ID`, distinct
from `CONFIRM_BUTTONS`' `confirm_yes`/`confirm_no` on purpose — see that
constant's own new comment on why a plan-level Yes needs its own row ids
even though both buttons read "Yes"/"No").

**`EDIT` built 2026-07-30** — §12's open question resolved as *"drop a step
and its dependents, re-preview"*, the option that open question itself
named as likeliest. Tapping Edit shows a picker (one `ListRow` per current
step, `describe_step` again for the label, plus a "Keep all" row to back
out unchanged) via `channel/replies.py`'s `render_plan_edit_picker`.
Tapping a step calls the new `PlanStore.remove_step`, which reuses
`mark_step_failed`'s exact `_transitive_dependents` closure — removing the
project also removes the site under it, for the same reason ADR-C4 cancels
a dependent step that failed — but **deletes** rather than marks
`CANCELLED`: nothing was ever attempted, so nothing belongs in the eventual
closing summary. Removing every step clears the plan outright
(`render_plan_emptied_by_edit_reply`) rather than leaving an empty,
un-runnable husk in Redis. There is still no free-text edit and no
per-field edit — only "drop this whole step, or don't" — which is
deliberately the smallest change that closes the actual gap: before this,
a wrong step anywhere in a 5-step plan meant rejecting all five and
resending from scratch.

The sequencing this forced: `try_start_decomposed_plan`
(`runtime/inbound_journey/decomposed_plan.py`) no longer starts the plan —
it persists it all-`PENDING` and returns the preview. A new
`resume_pending_plan_confirmation` (`runtime/inbound_journey/
plan_confirmation.py`), dispatched from `message_journey.py`'s row-id chain
exactly like every other `resume_pending_report_with_*`, handles the tap:
No clears the plan (`render_plan_cancelled_reply`); Yes calls
`plan_executor.py`'s new `begin_plan` — the same `_start_next_runnable` loop
`start_plan` already used, now exposed separately so a plan can be
persisted-and-previewed first and begun-later, on a **different** message
(the Yes tap), rather than in one call. `start_plan` itself is kept for the
one producer that still wants persist-and-begin together: the
entity-resolution layer's 2-step member-create chain, which is already a
direct continuation of a confirmation the user just answered and doesn't
need a fresh preview of its own.

An all-`PENDING` plan is provably inert to every other confirmation in the
system while it waits: `plan_executor.advance_plan`'s `_running_step_for`
only ever matches a step whose status is `RUNNING`, and a freshly-persisted
preview plan has none — so nothing anywhere can accidentally advance it
before the user answers Yes.

---

## 9. Decomposition

> **⚠️ SUPERSEDED 2026-07-31 by [`UNIFIED_UNDERSTANDING_PIPELINE.md`](UNIFIED_UNDERSTANDING_PIPELINE.md).**
> The `semantic_type == unknown` gate settled below is **retired, not
> re-tuned**. A second Malayalam trace of the same shape as the one that
> settled this section returned `add_project_member` at `high` confidence
> instead of `unknown`, so the gate missed it entirely and the user got a
> project picker that could not contain the project they had just asked to
> create. Two structurally identical messages, opposite classifications —
> see that doc's §1.2. The premise below ("for exactly the messages that
> need decomposing, `semantic_type` carries no signal at all") is disproved:
> it can carry a confident and wrong signal.
>
> The `intents[]` option this section weighed and rejected is now ADR-U1
> there. Its stated risk — regressing single-intent accuracy — was correct
> and is now that plan's governing risk and merge gate.
>
> **Kept below unchanged** as the record of why the gate was chosen, and
> because the deferred-required-field analysis at the end of this section is
> still accurate and still open.

Understanding returns exactly one `semantic_type`
([`understanding/pipeline.py`](../../apps/whatsapp-assistant/src/understanding/pipeline.py)).
Two options, both real:

| | Extend existing extraction to return `intents[]` | Separate decomposer call |
|---|---|---|
| Latency | None added | +1 call per message unless gated |
| Risk | Regresses single-intent accuracy on **every** existing path | Isolated |
| Effort | Prompt change across both adapters | New module |

**Settled 2026-07-30 by a real trace — separate call, gated on
`semantic_type == unknown`.**

A live Malayalam voice note asked for three things ("create a project called
Starship, then a site called Site A, then a new user Hysam — I'll send his
number"). It returned `semantic_type: unknown`, `confidence: high`,
`event_type: Unrecognized`, and the user got *"Hello. What are you reporting
today?"* after 6336 ms.

Two independent causes, both contract-level rather than model-level:

1. **`semantic_type` is single-valued.** The extraction prompt
   ([`gemini/adapter.py:72`](../../platform/ai/src/mesiri_ai/adapters/gemini/adapter.py))
   asks for one value from a closed enum, and grepping both the Gemini and
   DeepSeek prompts for any multi-intent provision returns zero. Three
   intents have no representable form.
2. **`create_user` was explicitly disqualified.**
   [`adapter.py:431`](../../platform/ai/src/mesiri_ai/adapters/gemini/adapter.py)
   says verbatim: *"if no number is stated anywhere in the message this is
   NOT create_user (it is more likely add_project_member or unrecognized)."*
   The sender promised the number in a follow-up, so no digits were present.

`unknown` was therefore the **correct** answer to the question actually
asked. The model was confidently reporting that the message is not one of
our categories, and it was right.

**This kills the original framing.** Decomposition cannot post-process the
primary `semantic_type`, because for exactly the messages that need
decomposing that field carries no signal at all. It must be its own call.

**And it hands us a near-free gate.** Rather than counting conjunctions:
run the decomposer only when `semantic_type == unknown`. That is a small
slice of traffic which today produces a useless greeting anyway, so the
worst case of a wasted call is a message that was already being discarded.
**No latency is added to any path that currently works.** `unknown` also
covers genuine gibberish and greetings, so the decomposer must be free to
answer "this really is one intent, or none" and fall through unchanged.

Decomposition runs on `translated_text`, so the Malayalam path is covered by
construction.

**A deferred required field — corrected 2026-07-30, was wrong as first
written.** This section originally claimed "no special handling: the step
runs, and `CREATE_USER`'s own `build_draft` asks for the phone number,
exactly as it does today." **Verified false** when wiring §9 into
`process_inbound_message`: `canonicalization/mapping.py`'s `REQUIRED_FIELDS`
requires `whatsapp_number` for `CREATE_USER_REQUESTED`, so a segment stating
only `full_name` ("create a new user Hysam, I'll send his number now")
canonicalizes to `CLARIFICATION_REQUIRED` — a `CanonicalEventType`
`planner/routing.py`'s `WORKFLOW_KEY_BY_EVENT` has **no entry for by
design** (its own docstring: `ClarificationRequired` never starts a
workflow). `build_plan_from_segments` therefore drops that segment exactly
the way it drops any other unroutable one — silently, correctly per its own
contract, but not what "the step runs and asks" implied.

Two other paths avoid this and were the source of the wrong assumption:
the single-message path gets `render_clarify_reply`'s targeted "Almost
there — I still need WhatsApp number" (`channel/replies.py`), and the
entity-resolution layer's offer-driven create (`resume.py`'s
`start_member_create_plan`) hand-builds its `CanonicalEventV2` and so never
passes through `REQUIRED_FIELDS` at all. Neither escape hatch exists for a
decomposed segment yet.

**Current, honest V1 behavior:** the project and site in that example still
get created — real progress — but the user-creation step is silently
dropped rather than asked about. Silence was the deliberate interim choice
over a misleading reply or a guessed phone number, not a considered design.
Surfacing it ("I couldn't create Hysam yet — also send me his number") is
real, un-scoped follow-up work, most naturally landing with the plan
preview (§8): the preview is where a dropped segment can finally be told to
the user instead of only logged. Test:
`test_a_deferred_required_field_drops_the_segment_from_the_plan` in
`test_decomposed_plan.py` names this gap explicitly so it isn't
rediscovered as a bug.

**Still open once the preview landed (2026-07-30): the preview does not yet
do this surfacing.** `render_plan_preview` describes the `Plan` it is
given, which by construction only ever contains the segments that survived
`build_plan_from_segments` — a dropped segment is simply absent from what
the user sees, with no line saying "and I couldn't include X". Closing this
means passing `DecomposedPlanResult.skipped` (already collected, already
carries index/text/reason) through to the preview renderer, appended as a
plain-language note below the numbered list. Not done in this pass; the
preview mechanism it depends on did not exist until this pass.

---

## 10. Phases

Numbered to slot alongside his phases (his §5), not to duplicate them. His
Phase 0 (doc + Module Placement Log row) is done — both docs now exist.

| Phase | Content | Owner | Status |
|---|---|---|---|
| **0** | §4.4 confirmed in writing in his doc: his continuation is built on `Plan`/`PlanStep`/`PlanStore` (§6, this doc), not a standalone `PendingReportStore` generalization. | Joint — his doc, this ask | **Done** — accepted in his §8.1, commit `0074fae`. |
| **1** | `EntityType`, `Resolved`/`Ambiguous`/`Missing`, registry `provides`/`requires`, `Plan`/`PlanStep`/`PlanStore` primitives built together (not sequentially) so his continuation is the first real consumer. | His doc, jointly-designed store | **Done** — commit `ee3cd7b`. Shipped N-capable, with §11.1's two gaps. |
| **2** | Migrate USER (his live bug) — a `Plan` of size 2 (create_user → add_member). | His doc | **Done** — `ee3cd7b`, `1ba6462` (stale-plan hijack fix), and `4ae4a67` (swapped onto the generic executor, `plan_executor.advance_plan`/`begin_plan` — the hand-written `advance_member_plan_after_user_created` is deleted outright). Verified against a *real* `WorkflowRuntime` + compiled LangGraph graphs, not just fakes (`test_member_create_plan_real_runtime.py`) — not yet against a live WhatsApp send. |
| **3** | Migrate MATERIAL — must reproduce `resume_pending_report_with_material_create` exactly via the shared store. | His doc | **Done** — `fe1c257`. |
| **4** | Decomposition (§9) + plan preview (§8). Ordering (§7.1), just-in-time canonicalization (§7.2, `planning/binding.py`) and dependency-aware cancellation (§7.4) were already built and tested. | This doc | **Done** — `9078fdd` (decomposition wired into `process_inbound_message`), `4ae4a67` (executor swap, prerequisite for one-plan-one-executor), and the preview (`planning/preview.py`, `runtime/inbound_journey/plan_confirmation.py`, this commit). The Paraclette/Starship message works end to end, gated behind Yes/No. |
| **5** | Migrate ACCOUNT/VENDOR/AUDIENCE/PROJECT/SITE, deleting each bespoke resolver. | His doc | In progress — `ba1d3ed` migrated VENDOR. |
| **6** | Whole-plan permission pre-check (§7.3) — via the real gates or one extracted predicate, **not** by promoting `allowed_roles` (ADR-C5 withdrawn, see his §8.2). Separate security review. | This doc | Not started. |

Phase 1 was the one place both docs' timelines actually merged — building the
store once, together, is what made §4.4 true rather than aspirational, and
it worked: the entity-resolution layer's continuation is `PlanStore`'s first
real consumer, so there is one executor to extend rather than two to
reconcile. Phase 4 inherits a store already exercised by a real chain, which
is also how §11.1's two gaps were found before they cost anything.

---

## 11. Where work stopped / what to do next

**Phase 1 is done and committed** (2026-07-30, jointly with the
entity-resolution layer — see its §8.1). Landed: `EntityType`, registry
`provides`/`requires` + `workflow_that_provides`,
`Plan`/`PlanStep`/`StepRef`/`PlanStore`/`topological_order` under
`planning/`. §4.4 was accepted, so there is **one store and one executor** —
that layer's continuation is built on `PlanStore`, not a parallel mechanism.

Phases 2–3 of this doc are effectively absorbed: `PlanStore` shipped
N-capable from the start rather than as a size-1 store to widen later, and
its first real consumer is that layer's `start_member_create_plan` /
`advance_member_plan_after_user_created`.

**Next action is Phase 4** (decomposition + ordering + preview). Before it
starts, §11.1 must be closed — Phase 1 shipped with two known gaps that Phase
4, and nothing before it, will hit.

Resolved already, no further action needed:

1. ~~Field names~~ — `provides`/`requires`, matched independently, adopted (§4.1).
2. ~~`EntityType` location~~ — `workflows/registry.py` / new `workflows/entities.py`, not `shared/contracts` (§4.2).
3. ~~`allowed_roles` reuse~~ — see §4.3, and his §8.2 objection, which this
   doc now concedes: ADR-C5 is **withdrawn as written**. Promoting an
   advisory field to load-bearing inverts its safety property (drift becomes
   a privilege bug rather than a wrong menu row). Phase 6 instead checks
   plans against the real gates, or extracts one predicate both call.
4. ~~Shared store~~ — §4.4 accepted and built (his §8.1).

### 11.1 Phase 1's two known gaps — ✅ CLOSED 2026-07-30

**Both fixed.** `PlanStep` now carries `event_type` and keeps `fields` and
`scope` apart; `Plan` carries `organization_id` / `permissions` /
`conversation_id` / `source_message_id`; and the new `planning/binding.py`
rebuilds a complete `CanonicalEventV2` per step just-in-time. The
entity-resolution layer's two hand-rolled workarounds (`_resolve_step_field`
and the `resolved_fields.pop("project_id")`) are deleted — it now calls
`build_event` like any other consumer will.

Verified: the real Starship voice note is expressible and executable as a
3-step plan, with the site step's project resolving to the project step's
output and landing on `event.project_id`, not in `fields`.

The original statement of both gaps is kept below, because the *reasoning*
is what stops them being reintroduced.

**(a) `PlanStep` cannot reconstruct a `CanonicalEventV2`.**
`workflow_runtime.start()` requires a real event, and `PlanStep` stores only
`workflow_key` + `fields`. That is lossy twice over:

- `workflow_key` → `event_type` is **many-to-one and therefore not
  invertible**: `SITE_UPDATE` ← 2 event types, `SITE_ISSUE_CLOSE` ← 3,
  `PETTY_CASH` ← 2, `REVERSE` ← 2 (`planner/routing.py`).
- `permissions`, `organization_id`, `conversation_id`, `source_message_id`,
  `causation_id`, `completeness`, `missing_fields` are all dropped. `Plan`
  carries `user_id` but not org.

Today the resolution layer hand-builds a fresh `CanonicalEventV2` at start
time, which works because it knows exactly which two workflows it is
chaining. A decomposer emitting arbitrary steps cannot.

Note `PendingBatchStore` — the existing multi-segment machinery — stores full
`CanonicalEventV2` objects per segment and does not have this problem. The
likely shape: `PlanStep` carries a full event when the step is canonicalizable,
and an unbound spec only while refs are still open.

**(b) `StepRef` has no destination, and the implied default is wrong.**
`site_create/nodes.py` reads `state["project_id"]` and its docstring is
explicit — the project comes from context resolution, *"never from
`collected_fields`."* A `StepRef` sitting in `PlanStep.fields` lands in
`CanonicalEventV2.fields`, the wrong place; `CanonicalEventV2` is
`extra="forbid"`, so scope cannot be smuggled through either. The resolution
layer works around this today with an explicit
`resolved_fields.pop("project_id")` before building the event.

Phase 4 needs the fields-vs-scope split to be explicit in the data structure —
roughly `field_refs` (→ `CanonicalEventV2.fields`) vs `scope_refs` (→
`project_id` / `site_id`) — rather than every consumer remembering to
re-route by hand. This is the actual hard part of ADR-C2.

---

## 12. Open questions

- **Decomposition trigger** (§9): heuristic gate, or always-on second call?
  Wants latency measurement on real traffic.
- ~~**`EDIT` scope**~~ **Closed 2026-07-30** — drop a step and its
  transitive dependents, re-preview, exactly as guessed here. See §8 and
  `PlanStore.remove_step`.
- **Plan TTL.** `PendingBatchStore` uses 30 minutes. A five-step plan with a
  disambiguation round may legitimately outlive that.
- **Idempotency on re-delivery.** WhatsApp redelivery mid-plan. `pop_once`
  covers the current batch; a plan with committed steps needs a stronger
  guarantee.
- **Do informational steps belong in a plan at all?** ("create the project
  and tell me the cement stock.") Probably yes, unordered and exempt from the
  single-active gate, as they are today.

---

## 13. Test strategy

- **Ordering**: pure unit tests over the registry declarations. No LLM, no
  Redis. Every pair in the registry, plus cycle detection.
- **Binding**: the three §7.2 cases, each with an existing and a non-existing
  entity.
- **Regression anchor**: the existing material→activity batch must behave
  **identically** after Phase 2. It is the only multi-segment case that works
  today and is therefore the strongest correctness check available.
- **Scenario**: the Paraclette message, and its Malayalam equivalent, as
  end-to-end fixtures under `scenarios/`.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| **Two orchestrators** (§4.2) | **REOPENED 2026-07-31 — this row was wrong.** Closed only for the *entity-resolution* layer (§4.4 accepted; one `PlanStore`, one executor, built once in Phase 1). It was never true of [`workflows/batch.py`](../../apps/whatsapp-assistant/src/workflows/batch.py) + `PendingBatchStore`, which is live and wired ([`process.py:482`](../../apps/whatsapp-assistant/src/runtime/inbound_journey/process.py), [`dependencies.py:666`](../../apps/whatsapp-assistant/src/runtime/dependencies.py), [`interactions/handler.py:281`](../../apps/whatsapp-assistant/src/interactions/handler.py)) and sequences multi-segment messages with its own store, own advance path, own reply formatting, and **flat-FIFO failure semantics with no dependency notion**. §7 of this doc already prescribed that `PendingBatchStore` generalize into `PlanStore`; Phase 4 built them side by side instead, and marking this row "Closed" hid that in the one table meant to surface it. Unification is now specced as Phase A of [`UNIFIED_UNDERSTANDING_PIPELINE.md`](UNIFIED_UNDERSTANDING_PIPELINE.md). |
| Bad decomposition silently creates five wrong records | P3 — preview before any write. Decomposition ships last (Phase 4). |
| One YES grants project-manager rights | Accepted, with the full preview as the control. Revisit if it proves too loose in practice. |
| ~~Role gates promoted to registry data weaken enforcement~~ | **Closed by withdrawing ADR-C5** (his §8.2). Phase 6 uses the real gates or one extracted predicate; `allowed_roles` stays advisory. |
| Scope collision with the entity-resolution layer's `resume.py` collapse | §4.5 lists what this doc defers. Do not touch `resume.py` from this layer. |
| **A plan outlives its turn and attaches to the wrong workflow** | Realized once already (`1ba6462`): an abandoned plan hijacked a later unrelated `CREATE_USER`. Every advance/clear decision must match on `PlanStep.workflow_instance_id`, never on `workflow_key` alone. Phase 4 has N steps and so N times the exposure. |
| ~~Phase 1's two known gaps are rediscovered as bugs in Phase 4~~ | **Closed** — both fixed (§11.1). The reasoning is kept in the doc so they are not reintroduced; `SCOPE_KEYS` validation makes the fields-vs-scope mistake unrepresentable rather than merely discouraged. |
| **A disallowed step executes with no upfront refusal** | Confirmed 2026-07-30, not hypothetical: `plan_executor.py` and `decomposed_plan.py` have zero role/`actor` awareness, so `process.py`'s per-workflow role gates (`_PROJECT_CREATE_ROLES` etc.) — which only ever check the primary `canonical_event` — never run for any step inside a decomposed plan. Checked the backend independently: `application/projects/create_validation.py` re-validates the same role server-side, so this is **not a live authorization bypass** — but it means "should not even be an option" is violated for decomposed steps: a disallowed user taps through a multi-step preview before hitting a confusing rejection, instead of the option never appearing. This is Phase 6's job, now confirmed live rather than theoretical. |
| **The single-message gates never re-run per decomposed segment** | **Closed 2026-07-31** (project/site 2026-07-30, material-unit/stock 2026-07-31 — [`UNIFIED_UNDERSTANDING_PIPELINE.md`](UNIFIED_UNDERSTANDING_PIPELINE.md) Phase A5). Project-selection and site-selection: `_resolve_project_and_site` (`decomposed_plan.py`) runs once per decomposition (a sender-level property), auto-resolving the single-option case and otherwise holding the already-decomposed segment texts in `PendingDecompositionStore` while `render_project_picker`/`render_site_picker` ask. Material-unit-resolution and stock-sufficiency: genuinely per-segment (an ambiguous catalog name or an over-stock usage report is a property of one segment's own fields, not the sender), closed by `_process_remaining_segments`/`_run_segment_gates` building and gating each segment one at a time, pausing (holding `built_events`/`pending_event`/remaining `segments` in the same store) the moment any segment's own material-unit or stock gate needs to ask — five new resume legs answer the four gate outcomes, reusing `seeding.py`'s gate functions completely unmodified. |
| **Decomposition was unreachable in production** | Found 2026-07-30 while auditing the project/site gate work above, not by design review: `message_journey.py`'s real `process_inbound_message(...)` call sites never passed `decomposition=`/`plan_store=` (both silently defaulted to `None`), and `dependencies.py` never constructed a `DecompositionProvider` at all. Every commit since Phase 4 landed (`9078fdd`, `4ae4a67`, `c88d414`, `f8fc671`) was fully built and unit-tested but **dead code in the running app** — every UNKNOWN-classified message fell through to the ordinary unrecognized-message reply, never reaching `try_start_decomposed_plan`. Fixed in the same commit as the project/site gate: `dependencies.py` now builds `pending_decomposition_store` and passes the already-existing `ai_resolver` (`DynamicAIProviderResolver`, previously used only for `interaction_classifier`/`capability_help`) as `decomposition=`; `message_journey.py` threads `decomposition=`/`plan_store=`/`pending_decomposition_store=` through both real call sites and dispatches the two new picker-tap resumes. Verified via the full monorepo test suite (2633 passed) and the existing/new `decomposed_plan.py` unit tests, which exercise the real chain with fakes — **no live WhatsApp send has occurred**, so end-to-end production behavior remains unverified outside of tests. |

---

*Last updated: 2026-07-30 (Phases 0–2 done, §11.1 closed; Phase 4 next, unblocked; project/site gate closed and the decomposition-unreachable-in-production gap fixed)*
