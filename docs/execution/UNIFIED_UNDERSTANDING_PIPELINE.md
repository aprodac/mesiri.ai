> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Unified Understanding Pipeline — Design Doc

**Status:** Proposed, no code written (2026-07-31). Supersedes the *trigger*
design in [`COMPOSITE_REQUEST_PLAN_LAYER.md`](COMPOSITE_REQUEST_PLAN_LAYER.md) §9
and completes the *unification* that its §7 stated but never executed.
**Owner:** Ilan Usman
**Started:** 2026-07-31
**Last updated:** 2026-07-31
**Linear:** _(epic to be created — see §8)_

> **Resuming in a new session?** Read §2 first — it is the finding that
> motivates everything else. Then §4 (the target architecture), §5 (the
> decisions and what was rejected), and §8 (phases, in order — Phase A is
> deliberately risk-free and lands first).

> **Purpose of this document.** Durable memory for this change. If a future
> session — human or AI — loses all conversational context, this file alone
> should explain what is wrong today, what replaces it, why, in what order,
> and what evidence must exist before each phase merges.

---

## 1. The trace that started this

A real Malayalam voice message, 2026-07-31:

> ഒരു പുതിയ പ്രോജക്ട് ആഡ് ആക്ക് ബിദിലാജ് എന്നുള്ള പേരുള്ള ഒരു പ്രോജക്ട്
> എന്നിട്ട് പിന്നെ സൈറ്റ് എ എന്നുള്ള ഒരു സൈറ്റും ക്രിയേറ്റ് ചെയ്യ് പിന്നെ
> ഞാൻ ഒരു ഉസ്മാൻ എന്നുള്ള പേരിലുള്ള ഒരു എഞ്ചിനീയറിങ് സൈറ്റ് എഞ്ചിനീയറിങ്
> ആഡ് ആക്കണം അവന്റെ WhatsApp നമ്പർ ഞാൻ കുറച്ചു കഴിഞ്ഞ് അയച്ചു തരുന്നുണ്ട്

Translated by the pipeline itself:

> Add a new project, a project named Bidilaj, and then create a site called
> Site A. Then I need to add an engineer, a site engineer, named Usman. I
> will send his WhatsApp number a little later.

Transcription and translation are **correct**. What the pipeline then produced:

| Field | Value |
|---|---|
| `semantic_type` | `add_project_member` |
| `overall_confidence` | `high` |
| extracted fields | `member_name: Usman` |

Three requests in, one out. The project and the site are gone — not deferred,
not reported, not surfaced anywhere. And because `project_id` is unresolved
(Bidilaj does not exist), the message ends at
[`_run_project_gate`](../../apps/whatsapp-assistant/src/runtime/inbound_journey/seeding.py)
asking *"Which project is this for?"* over a list that **cannot contain
Bidilaj**, since creating it was one of the dropped intents.

The reply is not just wrong, it is confusingly wrong: it asks the user to
choose from the world as it was before the message they just sent.

### 1.1 Why the existing decomposition layer did not catch it

[`decomposed_plan.py`](../../apps/whatsapp-assistant/src/runtime/inbound_journey/decomposed_plan.py)
runs **only** when the primary extraction returns `semantic_type == unknown`
(its own module docstring states this as settled by trace evidence). Here
extraction returned `add_project_member` at `high` confidence, so the entire
composite-request layer — decomposition, entity-linking, ordering, the plan
preview, all of it — was never invoked.

**The gate is `unknown`. The signal needed is "is this several requests?".
Those are different questions, and they are not correlated.** A model can be
confidently wrong about arity. This one was.

### 1.2 The two traces — why the `unknown` gate is not salvageable

`COMPOSITE_REQUEST_PLAN_LAYER.md` §9 chose the `unknown` gate on
**2026-07-30, on the strength of a real trace**, and explicitly weighed and
rejected `intents[]` at that time. That decision was sound given the evidence
it had. One day later there are two traces, and they are nearly the same
message:

| | Trace A (2026-07-30) | Trace B (2026-07-31) |
|---|---|---|
| Language | Malayalam voice | Malayalam voice |
| Intents stated | 3 (project → site → user) | 3 (project → site → member) |
| Deferred field | "I'll send his number" | "I will send his WhatsApp number a little later" |
| `semantic_type` | **`unknown`** | **`add_project_member`** |
| `overall_confidence` | `high` | `high` |
| Decomposition ran? | **yes** — gate matched | **no** — gate missed |
| Outcome | 3-step plan, preview shown | 1 intent, project picker without Bidilaj |

Two structurally identical requests; opposite classifications; opposite
outcomes. §9's premise — *"for exactly the messages that need decomposing,
`semantic_type` carries no signal at all"* — is disproved by Trace B, where
it carried a confident and wrong signal.

**This is the fact that changes the decision.** The gate is not mistuned; it
is measuring a variable (was the model unsure?) that is independent of the
one that matters (how many requests are there?). §9's own reasoning that the
gate is "near-free" holds only if multi-intent reliably implies `unknown`,
and it does not. ADR-U1 reverses §9's choice on this evidence, not on
preference.

---

## 2. Root cause, and the larger finding

### 2.1 The schema makes the truth unrepresentable

```python
class ExtractionResult(BaseModel):
    semantic_type: str = "unknown"          # <- exactly one, always
    fields: dict[str, Any] = ...
```

There is **no value** `semantic_type` can hold that correctly describes the
Malayalam message. The model was asked "what is the intent of this text" and
answered honestly and confidently about one of the three it found. `high`
confidence is not a malfunction — it is a correct statement that
`add_project_member` really is in there.

This reframes the whole problem:

> The bug is not that decomposition is gated wrongly. The bug is that arity
> is decided by a field that cannot express it, and decomposition is a
> rescue path bolted on to catch the cases where that failure happened to
> coincide with low confidence.

No trigger heuristic fixes this, because every heuristic is a filter over a
signal (`unknown`, or lexical cues like *"then" / പിന്നെ / എന്നിട്ട്*) that
is a proxy for arity rather than a measurement of it. Tuning the proxy
trades false negatives for false positives forever.

### 2.2 Three mechanisms answer "how many things is this message?"

Auditing outward from the trace, the codebase answers that question in three
separate places, at three different stages, with three different vocabularies:

| # | Mechanism | Answer it can give | Fed by | Live? |
|---|---|---|---|---|
| 1 | `ExtractionResult.semantic_type` | "exactly 1", always | the extract call | yes |
| 2 | [`build_canonical_events`](../../apps/whatsapp-assistant/src/canonicalization/builder.py) → [`workflows/batch.py`](../../apps/whatsapp-assistant/src/workflows/batch.py) + `PendingBatchStore` | "1 or 2" — the deterministic `work_item` expansion only | canonicalization | **yes** — wired at [`process.py:482`](../../apps/whatsapp-assistant/src/runtime/inbound_journey/process.py) / [`dependencies.py:666`](../../apps/whatsapp-assistant/src/runtime/dependencies.py) |
| 3 | `decompose()` → `planning/` + `PlanStore` + `plan_executor` | "N" | a **second** LLM call, gated on `unknown` | yes, since 2026-07-30 |

Mechanisms **2 and 3 are two live orchestrators**. Both sequence several
`CanonicalEventV2`s with a confirmation between each. They do not share:

| | `workflows/batch.py` | `planning/` + `plan_executor.py` |
|---|---|---|
| Store | `PendingBatchStore` (30-min TTL) | `PlanStore` (own TTL) |
| Advance path | `interactions/handler.py:281` | `plan_executor.advance_plan` |
| Reply formatting | `format_batch_prefix`, `summarize_batch_outcome` | `format_plan_summary`, `render_plan_preview` |
| Failure semantics | flat FIFO — **no dependency notion** | transitive-dependent cancellation (ADR-C4) |
| Ordering | authored order | topological sort over registry `provides`/`requires` |

### 2.3 This was designed, then not executed

To be accurate about prior intent: `COMPOSITE_REQUEST_PLAN_LAYER.md` §7
already says —

> `PendingBatchStore` generalizes into `PlanStore` (same Redis key shape,
> same TTL reasoning, same pop-once discipline). `batch.py`'s formatting
> functions largely survive.

— and §3's **P5** states *"One plan, one executor… the principle that keeps
this layer and the entity-resolution layer from becoming two systems."*

So the unification was designed. Phase 4 then built `PlanStore` **alongside**
`PendingBatchStore` rather than replacing it, and §14's risk row
*"~~Two orchestrators~~ — **Closed**"* recorded the closure against the
entity-resolution layer only, which made the still-open batch duplication
invisible in the one table meant to surface it.

**Correction to that doc:** the "two orchestrators" risk is **not closed**.
It is closed for entity-resolution and open for `batch.py`. §9 of this doc
records the amendment.

---

## 3. Principles

- **U1 — Arity is measured once, at the one stage that reads the whole
  message.** Not inferred later, not rescued after a failure.
- **U2 — `n = 1` is the common case of the general path, never a separate
  path.** The moment single-intent has its own pipeline, the two drift, and
  every gate must be written twice (which is exactly what happened).
- **U3 — One plan, one executor.** Inherited verbatim from
  `COMPOSITE_REQUEST_PLAN_LAYER.md` P5. This doc finishes enforcing it.
- **U4 — Composing intents and competing interpretations are different
  axes.** `candidates` (existing) are rival readings of the same request;
  `intents` (new) are distinct requests that must all happen. Conflating
  them would be unrecoverable — see ADR-U3.
- **U5 — The 95% path may not regress to fix the 5% path.** Single-intent
  accuracy is the gate on Phase B, enforced by the existing golden suite
  (§7), not by inspection.
- **U6 — Every stage deleted must have its behaviour preserved or its loss
  stated.** No silent capability drops during unification.

---

## 4. Target architecture

```
NormalizedMessage
      │
      ▼
  EXTRACT ─────────────► intents: [i₁ … iₙ]        n ≥ 1, one LLM call
      │                                            (arity measured HERE, once)
      ▼
  CANONICALIZE ────────► events:  [e₁ … eₙ]        + deterministic work_item
      │                                              expansion (unchanged)
      ▼
  LINK ────────────────► StepRefs                  no-op when n = 1
      │
      ▼
  PLAN ────────────────► Plan(n steps)             n = 1 is the common case
      │
      ▼
  GATES per step ──────► project / site / material / stock
      │                                            structural, not per-path
      ▼
  CONFIRM ─────────────► n = 1: today's single confirmation (unchanged UX)
      │                  n > 1: §8 whole-plan preview (Yes / No / Edit)
      ▼
  EXECUTE ─────────────► plan_executor              ONE executor
```

Four structural changes, in dependency order:

1. **`ExtractionResult.intents: list[ExtractedIntent]`** — arity becomes
   representable. `semantic_type` survives as a derived property
   (`intents[0].semantic_type`) through the migration window.
2. **`build_canonical_events` becomes genuinely plural** — one
   `CanonicalEventV2` per intent, *plus* the existing deterministic
   `work_item` → `ACTIVITY_CONTINUATION` expansion, which is a real derived
   segment and stays. `build_canonical_event` (singular) becomes a thin
   `events[0]` shim.
3. **Everything becomes a `Plan`.** `process.py` stops branching between
   single / batch / decomposed. `workflows/batch.py` and `batch_store.py`
   are deleted; their callers repoint at `plan_executor`.
4. **Gates run per step by construction** — because there is only one path
   through which a step can reach execution.

### 4.1 What this fixes that today's design cannot

| Symptom | Today | After |
|---|---|---|
| Confident-but-multi message (the trace) | silently truncated to 1 intent | n intents, all planned |
| Gates skipped for decomposed segments | patched for project/site on 2026-07-30; material/stock still open | structural — one path, gates run once, for every step |
| Two orchestrators | live, divergent failure semantics | one |
| A dropped required field (Usman's number) | segment silently vanishes from the plan | still open — see §10, but now in **one** place to fix rather than three |

### 4.2 The deferred-field interaction (still open after this change)

The same trace states *"I will send his WhatsApp number a little later."*
`CREATE_USER_REQUESTED` requires `whatsapp_number`
([`mapping.py:188`](../../apps/whatsapp-assistant/src/canonicalization/mapping.py)),
so that intent canonicalizes to `CLARIFICATION_REQUIRED` and
`build_plan_from_segments` drops it — the known V1 gap already documented in
`test_decomposed_plan.py::test_a_deferred_required_field_drops_the_segment_from_the_plan`.

This unification **does not fix that**, and must not be described as if it
does. What it changes is that after Phase A there is exactly one place where
the fix belongs (the preview's "I couldn't include X yet — also send me Y"
line), instead of three paths that would each need it.

---

## 5. Decisions

### ADR-U1 — Merge arity into extraction; do not add a segmentation stage

**Decision.** Extraction returns `intents: list[...]`. There is no separate
segmentation call.

**This reverses `COMPOSITE_REQUEST_PLAN_LAYER.md` §9**, which weighed this
exact option on 2026-07-30 and chose the gated separate decomposer instead.
That choice was correct on its evidence; §1.2 here is the new evidence that
invalidates its premise. Note that §9's stated reason for rejecting
`intents[]` — *"regresses single-intent accuracy on every existing path"* —
was **right**, and is not dismissed: it is now the governing risk of Phase B
and the entire subject of §7's merge gate.

**Why.** The model already reads the entire message in the extract call.
Asking *"list every distinct request you see"* instead of *"what is the
request"* is the same call, same tokens, same latency, same cost. A separate
pre-pass would add one LLM round trip to **every** message — including the
~95% that are single-intent — to recover information the extract call
already had and was structurally prevented from returning.

**Rejected alternative: unconditional segmentation stage before extraction.**
Keeps the extraction prompt untouched (its only real advantage — zero
regression risk on the 95% path), but pays a permanent latency and cost tax
on every message, and creates split-brain: two models independently
reasoning about boundaries, where a segmenter saying "2" and an extractor
confidently classifying segment 1 as something spanning both is
unresolvable. Reconsider only if §7's golden-suite gate proves
un-passable — that is the one outcome that would make the tax worth paying.

**Rejected alternative: keep `decompose()` as a second opinion.** The
argument for keeping it is robustness — one bad call loses everything. But
that is already true today: one bad extraction call already loses everything,
which is precisely this trace. A stage that only runs after a failure cannot
improve a case where the failure was silent and confident.

### ADR-U2 — `n = 1` produces a Plan too

**Decision.** Every message produces a `Plan`, including single-intent ones.
The `n = 1` path differs only in **presentation** (today's single
confirmation, not the whole-plan preview) — a branch on `len(plan.steps)`
at the reply layer, not a separate pipeline.

**Why.** U2. The gate gap fixed on 2026-07-30 existed *because* single-intent
and decomposed were separate paths, so gates written for one never ran in
the other. Fixing that by re-adding gates to the second path (what was done
on 2026-07-30, for project/site only) treats the symptom. Collapsing the
paths removes the class of bug.

**Cost, stated plainly.** Every single-intent message now allocates a `Plan`
and a `PlanStore` write it did not before. This is one extra Redis
round trip on the hot path — measured, not assumed, before Phase A merges
(§7).

### ADR-U3 — `intents` is a new axis, not a reuse of `candidates`

**Decision.** Add `intents`. Do **not** overload `candidates`.

**Why.** `UnderstandingResult.candidates: list[Candidate]` already exists and
is already a list — the tempting shortcut. But
[`_select_candidate`](../../apps/whatsapp-assistant/src/canonicalization/builder.py)
picks the single candidate matching `understanding.semantic_type`, because
candidates are **rival interpretations** of one request (ambiguity — see
`planner/ambiguity.py`). Intents are **co-occurring** requests, all of which
must execute. Overloading one list to mean both would make "did the user ask
for two things, or might they have meant one of two things?" unanswerable,
and `planner/ambiguity.py` would silently start treating separate requests
as competing readings. Two axes, two fields.

### ADR-U4 — `workflows/batch.py` is deleted, not extended

**Decision.** Delete `batch.py` + `batch_store.py`. Preserve their
formatting behaviour by porting it into the plan reply layer.

**Why.** U3/P5, and §2.3 — this is what §7 of the prior doc already
prescribed. `batch.py`'s flat FIFO has no dependency notion, so keeping it
would mean the material→activity case permanently runs under weaker failure
semantics than every other multi-step case.

**Non-negotiable preservation.** The material→activity batch is the only
multi-segment case that works in production today. Its behaviour is the
regression anchor (§7) — it must be byte-identical in reply text before and
after, which the prior doc's §13 also demanded.

---

## 6. Contract changes

### 6.1 `ExtractionResult` (platform/ai — internal model)

```python
class ExtractedIntent(BaseModel):
    """One distinct request found in a message. Composing, not competing
    (see ADR-U3)."""
    semantic_type: str = "unknown"
    fields: dict[str, Any] = Field(default_factory=dict)
    unknown_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    source_span: str | None = None          # the sub-text this came from
    warnings: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    intents: list[ExtractedIntent] = Field(default_factory=list)

    # --- migration shims: derived, removed at the end of Phase B ---
    @property
    def semantic_type(self) -> str:
        return self.intents[0].semantic_type if self.intents else "unknown"

    @property
    def fields(self) -> dict[str, Any]:
        return self.intents[0].fields if self.intents else {}
    # (unknown_fields / missing_fields / field_confidences likewise)

    # unchanged, message-level not intent-level:
    detected_language: str | None = None
    transcript: str | None = None
    translated_text: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: float | None = None
```

**Normalization invariant** (mirrors `DecompositionResult._normalize`'s
instinct, which is the one piece of the deleted layer worth keeping):
an empty `intents` list normalizes to a single `unknown` intent, so
"no intents" is never representable downstream.

### 6.2 `UnderstandingResult` (shared/contracts — the M3 output contract)

Same shape: add `intents: list[Candidate]`, keep `semantic_type` and
`candidates` as derived properties through the migration. `model_config =
{"extra": "forbid"}` means this is a **versioned contract change** —
`CONTRACT_VERSION` stays `v1` only if the derived properties keep every
existing consumer valid; otherwise it goes to `v2` and
`M2_M3_INTEGRATION_CONTRACT.md` needs the corresponding row.

### 6.3 Blast radius (measured 2026-07-31)

| | Count |
|---|---|
| `.semantic_type` read sites, non-test | **15**, across **6** files |
| …of which are the real structural consumer | `canonicalization/builder.py` (5), `planner/ambiguity.py` (2) |
| …of which are set-sites | `understanding/pipeline.py` (4) |
| …of which are display/logging only | `understanding/runtime.py`, `process.py:331`, `scripts/verify_m2_m3_direct.py` |
| `decompose()` implementations to delete | 5 files (2 adapters, port, resolver, fakes) |

### 6.4 Code deleted

| File | LOC |
|---|---|
| `workflows/batch.py` | 161 |
| `workflows/batch_store.py` | 151 |
| `runtime/inbound_journey/decomposed_plan.py` | 377 |
| `runtime/inbound_journey/pending_decomposition.py` | 116 |
| `planning/decomposition.py` (the `decompose`-fed half) | 219 |
| `mesiri_ai/ports/decomposition.py` | 31 |
| **Total** | **~1,055** |

Plus the `decompose()` method in both provider adapters, the resolver, and
the fakes.

**Note for the record:** `decomposed_plan.py` and `pending_decomposition.py`
were written on 2026-07-30 (commit `333dfa1`, hours before this doc). They
are deleted here because they exist to rescue a schema that Phase B fixes at
the root. What survives from that work is everything underneath it —
`PlanStore`, `plan_executor`, `planning/ordering.py`, `planning/binding.py`,
`planning/outputs.py`, `planning/preview.py`, and the gate *logic* — which
becomes the single path rather than the second one.

---

## 7. Regression strategy — the gate on Phase B

**Decision (2026-07-31): the existing golden/scenario suite is the merge
gate.** The intents-plural prompt does not merge until every existing golden
and scenario test is green, unmodified.

Rationale and its limit, stated honestly: this directly measures "did
single-intent accuracy degrade" against cases already written down, and it
costs nothing to run. It does **not** cover message shapes nobody has
written a test for — a real-traffic replay set would, and remains the
stronger option if the golden suite proves too thin once the prompt changes
land (§10).

Concretely, before Phase B merges:

1. **Full monorepo suite green** — currently 2,633 passed / 16 skipped.
2. **Golden + scenario suites green with no test edits.** A test that needs
   editing to pass is a regression until proven otherwise, in writing, in
   this doc.
3. **The material→activity batch reply text is byte-identical** pre/post
   (ADR-U4's non-negotiable).
4. **Over-splitting probe**: a fixture set of deliberately-single-intent
   messages that a list-shaped prompt is most likely to wrongly split —
   *"I paid 5000 for cement"* (expense vs. expense+material), *"10 masons
   worked on the slab today"* (labour vs. labour+activity). These are new
   tests, and they are the specific failure mode ADR-U1 accepts risk on.
5. **The Malayalam trace in §1 becomes a scenario fixture** — 3 intents,
   correct order, with the `whatsapp_number` gap surfaced rather than
   silent (§4.2).

Phase A carries no AI-behavior risk and is gated on (1) + (3) only.

---

## 8. Phases

**Sequencing decision (2026-07-31): Phase A first, in full, before Phase B
starts.** The orchestrator unification is pure refactoring with a
deterministic test gate; the schema change is the one with model-behaviour
risk. Landing A first means B changes one prompt into an already-clean
pipeline, so any regression B causes is unambiguously B's.

### Phase A — Unify the orchestrators (no AI behaviour change)

| # | Step | Verification |
|---|---|---|
| A1 | Extend `PlanStore`/`plan_executor` to cover what `PendingBatchStore` does: running outcome log, `(2 of 3)` progress prefix, closing summary. Port `format_batch_prefix` / `summarize_batch_outcome` behaviour into the plan reply layer. | Unit tests on the ported formatters, asserting identical output strings. |
| A2 | Repoint `build_canonical_events`' multi-event output at `build_plan_from_segments` instead of `batch_store.start_batch`. The `work_item` expansion becomes a 2-step Plan. | The material→activity regression anchor, byte-identical. |
| A3 | Repoint `interactions/handler.py:281`'s batch-advance at `plan_executor.advance_plan`. Delete the `batch_store` branch. | Full suite; the single-active invariant (§7.5 of the prior doc) must still hold. |
| A4 | Make `n = 1` produce a Plan. Reply layer branches on `len(plan.steps)`: 1 → today's confirmation, >1 → preview. | Full suite green with **zero** reply-text changes for single-intent messages. |
| A5 | Move the gates so they run per step. Deletes the 2026-07-30 project/site special case in `decomposed_plan.py` and closes the material/stock half structurally. | The gate tests from `test_decomposed_plan.py` re-pointed at the unified path. |
| A6 | Delete `workflows/batch.py`, `workflows/batch_store.py`, and their wiring in `dependencies.py` / `message_journey.py` / `process.py`. | Full suite; grep for orphaned references. |
| A7 | Measure the added `PlanStore` write on the single-intent hot path (ADR-U2's stated cost). | A latency number recorded in this doc, not an assumption. |

#### A1 — done 2026-07-31. Two decisions made while implementing, recorded here:

**The progress prefix and per-step confirmation rendering needed no porting.**
`_progress_prefix` and `render_workflow_run_reply_spec` in
`runtime/plan_executor.py` already reproduce `format_batch_prefix` and
`render_started_segment_reply_spec`'s wording/shape exactly — built that way
deliberately when `plan_executor.py` was first written (its own comments say
so). The real gap was narrower than A1's original framing: only the
**closing-summary outcome line** lost information, because `PlanStep.status`
(DONE/FAILED/CANCELLED) cannot express *why* — a domain rejection reason, a
conflict note — the way `workflows/batch.py`'s `summarize_batch_outcome`
(fed by the live `WorkflowResumeResult` + `ExecutionResult`) can.

**Fix:** added `PlanStep.outcome_detail: str | None`, computed in
`advance_plan` via `_summarize_step_outcome` (ported verbatim from
`summarize_batch_outcome` — same wording, same branches, see
`test_summarize_step_outcome_matches_workflows_batch_wording_exactly`).
`_outcome_line` prefers it when present, falling back to the old
status-only wording only for a step that never got an execution result
(CANCELLED, or a bind/start failure). This is a **strict improvement**, not
a preserved bug: a `FAILED` step's summary line now names the actual reason
instead of a generic "couldn't be completed." Two existing tests asserted
the old generic wording and were updated to the richer one
(`test_plan_executor.py`, `test_member_create_plan.py`) — both are
disclosed wording upgrades, not silent regressions.

**Decision, not yet applied: the closing message stays its own standalone
send, not glued onto the last step's own reply.** `workflows/batch.py`
appends `format_batch_summary`'s output onto the last resolved segment's own
`reply_text` (one WhatsApp message, two parts). `plan_executor.py` sends the
summary as an entirely separate follow-up message once every step is
terminal — this is the shape the Starship/decomposed-plan preview already
uses, and unifying onto batch's append-based composition would be a second,
larger change (restructuring where `format_plan_summary`'s output is
attached) than "port the formatting." Deferred to A2, where the
material→activity live case actually moves onto this path and the
difference becomes user-visible for the first time — see A2's own note once
written.

**The header wording change is real and accepted, not hidden.** The closing
line reads `*Here's what I did:*`, not `workflows/batch.py`'s
`*Batch summary:*` (with its leading blank-line separator, meaningful only
in the append composition above). No test asserts `"Batch summary"` against
a live end-to-end reply — `test_batch_workflow.py`'s assertions are unit
tests on `batch.py`'s own functions in isolation, and that file is deleted
in A6 along with everything it tests. So this is a genuine, disclosed
wording change for the one live user-facing case (material→activity), made
because "one plan, one wording" (U3) is the point of this whole doc — not
an oversight discovered later.

#### A2 — done 2026-07-31.

`process.py`'s kickoff now branches on `extra_segments`: the primary
segment (`canonical_events[0]`) still runs through the exact same inline
code as every ordinary single-segment message (unchanged gates,
`workflow_runtime.start`, mlog/tlog calls) — `n = 1` still fully unchanged,
as A2 was scoped to leave for A4. When there ARE extra segments, the whole
`canonical_events` list (not just the extras) goes through
`build_plan_from_segments`, persisted via `plan_store.start_plan`, with the
already-started primary step (`step_id` is always `"s1"`, assigned before
`topological_order` can reorder the tuple — verified against
`planning/decomposition.py`'s own contract) marked `RUNNING` against the
`WorkflowInstance` that already exists, never started a second time. The
prompt gets the same `"(1 of N) "` prefix as before, computed by reusing
`runtime.plan_executor._progress_prefix` directly (a cross-module
underscore import, matching this codebase's existing convention for
`runtime.inbound_journey._shared._log`) rather than reimplementing it.

**The regression anchor this doc named did not exist.** Before this pass,
no test drove a work_item-linked material report through
`process_inbound_message` end-to-end — `test_multi_segment_canonicalization.py`
only tests `build_canonical_events` in isolation, and `test_batch_workflow.py`
only tests `workflows/batch.py`'s own functions in isolation, never wired
together through the real journey. Written as
`test_process_multi_segment_plan.py` in this pass, exercising the real chain
(real `ContextResolver` against `context/seed`'s fixtures, real `Planner`,
real `WorkflowRuntime` against a fake compiled graph, real
`build_plan_from_segments`).

**That new test caught a real bug in the first draft of this change**, not a
pre-existing one: `plan_store.mark_step_running(user_id=actor_user_id, ...)`
raised `PlanNotFoundError` because the test itself passed the wrong value
for `actor_user_id` — a raw fixture label (`seed.USER_ENGINEER`,
`"user_engineer"`) instead of the deterministic UUID
`context_resolver.resolve()` actually assigns
(`context.identity_bridge.deterministic_canonical_uuid`), which is what
real production wiring passes (`message_journey.py`'s
`actor_user_id=ctx.user_id`). Once fixed, the test passes and confirms the
production code path (`process.py`'s new branch) was correct as written —
the bug was in the test's setup, not the source change, but it is recorded
here because it demonstrates exactly why writing the missing anchor
mattered: without it, a user_id mismatch of this shape would have shipped
undetected (both `PlanStore.start_plan` and `mark_step_running` degrade to a
logged exception, per the module's "never take down the primary segment"
posture — see the `try/except` around the whole block in `process.py` — so
in production this class of bug would silently mean the second segment
never gets planned, not a visible crash).

#### A3 — done 2026-07-31.

**Finding, before any deletion happened:** the batch-advance branch in
`interactions/handler.py`'s `_resume_and_render` (checking
`self._batch_store.has_pending(...)`) was **already dead** the moment A2
landed — A2 stopped calling `batch_store.start_batch(...)` from
`process.py`, so nothing populates `PendingBatchStore` for any NEW message
after that commit. `has_pending` is provably always `False` going forward by
code inspection alone (the two systems share no state), not something that
needed a dynamic test to discover. A3's actual work was therefore deletion
and confirmation, not a functional fix:

- Removed the whole `if self._batch_store is not None and self._planner is
  not None:` block from `_resume_and_render`; `next_segment_reply` is now
  always the literal `None` it computed anyway.
- Removed the now-unused `planner`/`batch_store` constructor parameters and
  the `workflows.batch`/`workflows.batch_store` imports from
  `interactions/handler.py`, `interactions/builder.py`, and the
  `build_interaction_handler(...)` call site in `dependencies.py`. `Planner`
  had no other use in `handler.py` — confirmed by grep before removing the
  import.
- `InteractionHandled.next_segment_reply` itself is **kept** (not deleted) —
  `message_journey.py` still reads it (`if handled.next_segment_reply is not
  None: ...`), and removing the field is bundled into A6, when
  `workflows/batch.py` itself (and the reply-shape it produced) goes away
  entirely rather than leaving an orphaned import in the meantime.

**Verified, not assumed:** extended
`test_process_multi_segment_plan.py` with
`test_confirming_the_primary_segment_advances_to_the_linked_activity`,
which drives the exact call sequence `message_journey.py` makes —
`interaction_handler.handle_fast_path(...)` (the real handler, unmodified
call site) followed by `plan_executor.advance_plan(...)` — against a shared
`WorkflowRuntime`/repo so the confirmation resolves the same
`WorkflowInstance` the initial message started. Asserts both halves of A3's
claim: `handled.next_segment_reply is None` (the dead branch produces
nothing) and the second step (`SITE_UPDATE`) reaches `RUNNING` with the
right `"(2 of 2) "`-prefixed prompt (the generic `plan_executor` mechanism,
already proven abstractly by `test_plan_executor.py`, now proven for this
concrete origin/workflow-key pair too). Needed a fake `ExecutionDispatcher`
(mirroring `test_completion_photo_followup_trigger.py`'s own) since M8's
real dispatcher isn't reachable from this environment (no DB) — without one,
`execution_result` stays `None` and `advance_plan` would mark the step
`FAILED` rather than `DONE`, silently preventing the second step from ever
starting.

Full monorepo suite after these changes: 2641 passed, 16 skipped
(pre-existing), 213 deselected.

#### A4 — done 2026-07-31.

**The subtlety this step actually turned on, found before writing any
code:** the initial confirmation prompt was never the hard part —
`_progress_prefix` already returns `""` for a size-1 plan regardless of
origin, so the starting side of A4 falls out for free the moment
`process.py`'s existing plan-building block (from A2) runs unconditionally
instead of only `if extra_segments`. The **closing** side is where a naive
version of A4 would have shipped a real, user-visible regression:
`_start_next_runnable`'s "nothing left to run" branch already sends
`format_plan_summary(plan)` for *any* plan reaching terminal status,
including size 1 — proven by two already-existing, already-passing
`test_plan_executor.py` tests
(`test_the_last_step_completing_clears_the_plan_and_returns_a_summary`,
`test_start_plan_with_no_runnable_step_reports_the_summary_immediately`)
that build size-1 plans and assert the summary DOES appear. Making every
single-intent message a plan without a further decision would mean every
ordinary confirmed report gets a **second, redundant** `"*Here's what I
did:*\n1. …: Recorded."` message on top of the one `interactions/handler.py`
already sends — exactly the regression A4's own verification bar
(docs table above) rules out.

**Why step count alone can't be the suppression key.** A decomposed message
can legitimately produce a size-1 plan too — §9 of the prior doc's "deferred
required field" example (`test_decomposed_plan.py`'s
`test_a_deferred_required_field_drops_the_segment_from_the_plan`): 2 segments
decomposed, 1 dropped as unroutable, leaving a real 1-step `Plan`. That
user DID see an upfront "I'll do this: 1. Create project Starship" preview,
so a closing summary once it resolves is consistent, expected UX for them —
suppressing by step count would have silently changed that scenario's
behavior too, which A4 has no business touching.

**Resolution:** a new `PlanOrigin.SINGLE_MESSAGE` value, set only by
`process.py`'s kickoff when there are no extra segments (`extra_segments`
empty ⇒ `SINGLE_MESSAGE`; otherwise still `DECOMPOSITION`, unchanged).
`_start_next_runnable` suppresses the closing summary (`return None`)
specifically for `origin is PlanOrigin.SINGLE_MESSAGE` — never by
`len(plan.steps)`. This leaves every existing size-1 `DECOMPOSITION`-origin
case (the deferred-field scenario above, and the two `test_plan_executor.py`
tests, which build plans with an explicit non-`SINGLE_MESSAGE` origin)
completely untouched.

**Verified, not assumed — the gap the design table itself named.** Neither
existing size-1 `test_plan_executor.py` test exercises the real
`process_inbound_message` → `interaction_handler.handle_fast_path` →
`advance_plan` sequence a live "Yes" reply actually goes through; both build
their `Plan` by hand. Added `test_process_single_message_plan.py`, mirroring
A2/A3's own real-chain pattern:
`test_ordinary_single_message_starts_with_no_plan_prefix_and_becomes_a_size_one_plan`
(the starting-side guarantee — asserts the reply has no `"(1 of 1) "` prefix
and the persisted plan is `origin=SINGLE_MESSAGE`) and
`test_confirming_the_single_step_produces_no_extra_closing_message` (the
closing-side guarantee this whole step exists for — asserts `advance_plan`
returns `None`, not a second `ReplySpec`, after the one real step resolves).

Full monorepo suite: 2649 passed, 16 skipped (pre-existing), 217
deselected (the extra deselected count is the other concurrently-developed
site-issue-cancel feature's new `provider`/`integration`-marked tests, not
this change).

#### A5 — done 2026-07-31. Scoped narrower than the original phase table row,
on purpose — the real gap turned out bigger and differently-shaped than "move
the gates so they run per step" implied.

**What tracing the gap actually found.** Project/site was already closed
(2026-07-30, `_resolve_project_and_site`) — nothing left to do there.
Material-unit/stock is genuinely different: each of the four gate outcomes
(ambiguous material picker, material-create offer, Stock Unit mismatch,
over-stock choice) has its own picker/resume shape, and every one of
`resume.py`'s five single-message resume legs is built around
`interactions/pending_report.py`'s `PendingReportStore` — one
`CanonicalEventV2`, no notion of "N more segments still to come." Making
these run "per plan step" the way A1–A4 unified execution would have meant
teaching `plan_executor.py` to pause and resume mid-step, a new state
machine with no existing precedent in that module. Given the choice
presented to the user (close it fully now / defer as documentation /
narrow to just the material picker), **"close it fully now"** was chosen —
but implemented at the layer where the existing hold-and-resume pattern
already lives (`decomposed_plan.py`/`PendingDecompositionStore`, the
same 2026-07-30 project/site mechanism), not inside `plan_executor.py`.
`workflows/batch.py`'s eventual deletion (A6) and the whole-plan preview's
own execution phase are unaffected.

**Mechanism.** `PendingDecomposition` gains two fields: `built_events`
(every earlier segment that already passed every gate) and `pending_event`
(the ONE segment currently paused mid-gate). `_process_remaining_segments`
builds each segment's `CanonicalEventV2` one at a time and runs
`_run_segment_gates` on it before moving to the next; a gate's pause
persists `built_events`/`pending_event`/`segments` (everything after the
paused one) and returns the picker. Five new resume legs
(`resume_pending_decomposition_with_material`/`_material_create`/
`_material_unit_choice`/`_unit`/`_stock_choice`) mirror `resume.py`'s own
five single-message legs almost line for line — the only structural
difference is "then continue the decomposition loop" where `resume.py` says
"then call `_plan_and_run`."

**`_run_segment_gates` reuses `seeding.py`'s gate functions completely
unmodified** — no risk to the single-message path, which never calls this
module. A throwaway `_NullPendingReportStore` swallows the gate functions'
own `set_pending` calls (meant for `PendingReportStore`, the wrong store
here); this module persists the real pause state itself.

**A real bug found and fixed before any test passed.** The first draft
called `_run_project_gate`/`_run_site_gate` again inside
`_run_segment_gates`, reasoning they'd be harmless no-ops since project/site
is already resolved. Three pre-existing tests
(`test_decomposed_plan.py`) immediately failed: `_run_project_gate` fails
**closed** — asks, or says "no projects" — the moment `project_id` is
`None`, regardless of *why*, including `actor is None`. But
`_resolve_project_and_site` deliberately treats `actor is None` as "no gate
applicable, fall through unresolved" (its own docstring calls this "the same
degrade every other optional dependency in this layer uses, not a new
failure mode"). Calling the gate again silently reintroduced the exact
failure mode resolution was built to avoid. Fixed by not calling
`_run_project_gate`/`_run_site_gate` from `_run_segment_gates` at all —
project/site is out of this phase's scope, confirmed by the existing test
suite, not assumed.

**Environment note, for the record.** While this phase was in progress, a
`git reset` occurred on this shared working tree mid-session (visible in
`git reflog` as `edac765 HEAD@{0}: reset: moving to HEAD`) that discarded
several files' uncommitted edits twice, requiring them to be rewritten from
this conversation's own record before recovery. Very likely caused by the
concurrently-active entity-resolution session's own git operations on the
same shared checkout (its own commits during this window are visible in
`git log`) rather than anything this phase's work did. Recorded here
because it is exactly the kind of shared-working-tree risk
`COMPOSITE_REQUEST_PLAN_LAYER.md`'s own git-discipline notes warn about,
and because a future session hitting the same symptom should not assume
its own edits are wrong before checking for this.

Full monorepo suite: 1687 passed (whatsapp-assistant alone), 16 skipped
(pre-existing), 26 deselected.

#### A6 — done 2026-07-31.

Deleted `workflows/batch.py` and `workflows/batch_store.py` outright, plus
their dedicated test files (`test_batch_workflow.py`, `test_batch_store.py`
— 24 tests removed with them). Both had been provably dead since A2/A3
repointed their one real caller (the material→activity kickoff in
`process.py`) onto `PlanStore`, and A3 deleted the dead advance-branch in
`interactions/handler.py` that read from them — this step is pure removal
of code nothing calls anymore, confirmed by grep before deleting, not a new
behavior change.

Removed the now-dead `batch_store` parameter and its `PendingBatchStore`
import from every file that still threaded it through even though nothing
read it: `runtime/dependencies.py` (stopped constructing it), `runtime/
inbound_journey/process.py` (dropped the unused parameter), and `runtime/
message_journey.py` (dropped the parameter from `build_message_handlers`
and the two `process_inbound_message(...)` call sites). Updated four
comments/docstrings that referenced the now-deleted files as if they were
still current (`planning/plan_store.py` ×2, `canonicalization/builder.py`)
to describe what actually exists today; left comments that already spoke in
the past tense about the retirement (`interactions/handler.py`,
`interactions/builder.py`, both written during A3) unchanged, since they
were already historically accurate.

Full monorepo suite: 2665 passed (24 fewer than before A6, exactly the
deleted tests — no other count changed), 16 skipped (pre-existing), 230
deselected.

#### A7 — done 2026-07-31.

Measured, not assumed, by instrumenting a call-counting fake Redis and
driving the REAL `PlanStore`/`plan_executor.advance_plan` code paths a
size-1 `SINGLE_MESSAGE`-origin plan actually takes — process.py's exact
kickoff sequence (`start_plan` → `mark_step_running` → `get_plan` for the
progress prefix) and `advance_plan`'s exact sequence for that plan's one
step resolving successfully (through to `_start_next_runnable`'s "nothing
left to run" branch, which clears the plan and — because of `PlanOrigin.
SINGLE_MESSAGE` — returns `None` rather than a closing summary, per A4).

| Stage | Redis round trips added |
|---|---|
| Kickoff (message arrives, workflow starts) | 3 `get_json` + 2 `set_json` = **5** |
| Confirmation (user taps Yes, step resolves) | 7 `get_json` + 3 `set_json` = **10** |
| **Total, full message lifecycle** | **15** |

**A real inefficiency found while measuring, not introduced by this phase:**
`PlanStore.mark_step_running` calls `self.get_plan(...)` directly, then
calls `self._replace_step(...)`, which calls `self.get_plan(...)` *again* —
two reads where one would do. This method was built in Phase 1 of the
original composite-request-plan-layer effort (long before this doc), so A4
did not introduce it — but A4 is what makes every ordinary single-intent
message pay for it, where before only a multi-segment message or the
entity-resolution layer's own chain ever called `mark_step_running` at all.
Not fixed here — A7's job was to measure, and fixing a shared `PlanStore`
method touches the entity-resolution layer's own live chain too, which
deserves its own change and its own verification, not a drive-by inside a
measurement task.

**What this costs in practice.** 15 sequential (not batched) Redis round
trips, split across two separate inbound HTTP requests (the initial message
and the later confirmation), each independently pays local network latency
— on a same-region/same-VPC Redis (the realistic deployment shape here,
matching the VPS setup this whole codebase targets), each round trip is
on the order of ~0.3–1 ms, so the two added stages cost roughly **1.5–5 ms
kickoff** and **3–10 ms on confirmation** — single-digit milliseconds
against a request whose own extraction call (the LLM round trip already
happening on every message, unrelated to this phase) costs hundreds of
milliseconds to low seconds. Not free, but not the cost that matters on
this path. No live Redis was reachable from this environment to confirm the
real network figure directly; the range above is a documented estimate
against typical same-region Redis latency, not a live measurement — stated
plainly as the one part of this number that is not directly verified.

### Phase B — Intents-plural extraction

| # | Step | Verification |
|---|---|---|
| B1 | Add `ExtractedIntent` + `intents` to `ExtractionResult` with derived shims (§6.1). No prompt change yet — adapters emit a 1-element list. | Full suite green, entirely unchanged behaviour. |
| B2 | Same for `UnderstandingResult` (§6.2). Decide `v1`-compatible vs `v2` and update `M2_M3_INTEGRATION_CONTRACT.md`. | Contract tests; `extra: forbid` compatibility check. |
| B3 | `build_canonical_events` maps one event per intent. | Existing multi-event test + new n>1 fixtures. |
| B4 | **Change the extraction prompt** in both adapters to return all intents. This is the risk step. | §7's full gate — all five items. |
| B5 | Migrate the 15 read sites off the shims; delete the shims. | Full suite; grep for `.semantic_type`. |
| B6 | Delete `decompose()` everywhere, `decomposed_plan.py`, `pending_decomposition.py`, the port, adapters, fakes, and the `unknown`-gated branch in `process.py`. | Full suite; §6.4's LOC accounting reconciles. |

#### B1 — done 2026-07-31.

Added `ExtractedIntent` (one distinct request — `semantic_type`/`fields`/
`unknown_fields`/`missing_fields`/`field_confidences`/`warnings`, exactly
`ExtractionResult`'s old per-intent fields moved onto their own model) and
`ExtractionResult.intents: list[ExtractedIntent]`. The six old fields
become `@property` methods reading `intents[0]`.

**The real risk in B1 was never the schema — it was the ~100+ existing call
sites across the monorepo that construct `ExtractionResult(semantic_type=
..., fields=...)` directly** (every adapter, every fake, every test
fixture), none of which are migrated until B5. Closed with a
`model_validator(mode="before")` that translates that legacy top-level
kwarg shape into `intents=[ExtractedIntent(...)]` before Pydantic
validates — so construction is untouched, and only *reading* `.intents`
directly (new code, from B3 onward) needs the plural shape at all. A
second `model_validator(mode="after")` normalizes a bare
`ExtractionResult()` (a real, existing pattern — `FakeExtractionProvider`'s
own default) to one default `ExtractedIntent()`, so "no intents" is never
representable — the same invariant `DecompositionResult._normalize`
already enforced for its analogous case, reused here rather than
reinvented.

**Verification, not assumption:** ran the full monorepo suite with zero
test-file changes anywhere outside this phase's own new tests — 2689
passed, unchanged from before B1. That result *is* the proof the migration
validator works: every one of those ~100+ legacy construction call sites
exercised it and came out byte-identical. Added `test_extraction_result.py`
(6 tests) covering what the wider suite can't see directly: legacy-kwargs
construction, bare `ExtractionResult()`, new-style `intents=[...]`
construction bypassing the legacy migrator correctly, every derived
property reading `intents[0]`, message-level fields (`detected_language`
etc.) staying untouched by the migrator, and the actual Bidilaj-trace shape
(§1) — three intents constructed directly, `events[0]`-style callers still
seeing a coherent single answer.

Full monorepo suite: 2695 passed (6 more than before — this phase's own new
tests), 16 skipped (pre-existing), 230 deselected.

#### B2 — done 2026-07-31.

**Correction to §6.2 above, made while implementing:** that section said
"add `intents: list[Candidate]`, keep `semantic_type` **and `candidates`**
as derived properties" — the `candidates` part was wrong and has been
struck. `candidates` is the competing-interpretations axis (`planner/
ambiguity.py` picks one of several rival readings); `intents` is composing
(all co-occur). ADR-U3 is explicit that conflating the two axes makes "did
the user ask for two things, or might they have meant one of two things?"
unanswerable — making `candidates` a derived view of `intents` would do
exactly that. `candidates` is untouched: still a real, independently
populated field, exactly as it always was.

**Also correctly NOT derived, unlike B1:** `semantic_type`/`missing_fields`/
`warnings` stay real fields too, not properties reading `intents[0]`.
`ExtractionResult` (B1) is constructed once, atomically, by an adapter —
turning its old fields into read-only properties was safe. `understanding/
pipeline.py` builds `UnderstandingResult` **incrementally**, across several
methods (`result.semantic_type = semantic`, `result.warnings.extend(...)`,
`result.missing_fields = list(...)`) — a read-only property has no setter,
so this construction style is fundamentally incompatible with the B1
approach. Making it compatible would mean rewriting `_apply_extraction`/
`_apply_deterministic_shortcut` to build a whole `Candidate` first and
assign `result.intents` once at the end — real, valid future work, but a
larger rewrite than "B2: add the field," so left as a genuine field
addition. `CONTRACT_VERSION` stays `v1`: adding an optional field with a
default is backward compatible, and `M2_M3_INTEGRATION_CONTRACT.md` needed
no update — it documents the M2→M3 **input** contract
(`NormalizedMessage`), not `UnderstandingResult`'s own output fields.

**Implementation:** `understanding/pipeline.py`'s `_apply_extraction` now
also sets `result.intents` — one `Candidate` per `extraction.intents[i]`
(new `_build_candidate_from_intent` helper, mirroring the existing
`_build_candidate`'s construction exactly, generalized to read an
`ExtractedIntent` instead of `ExtractionResult`'s own `intents[0]` shim).
`_apply_deterministic_shortcut` (the greeting/who-am-i fast path, no
extraction call at all) sets a single trivial `Candidate(semantic_type=...)`
— `intents` must never be empty, the same invariant B1 enforces on
`ExtractionResult` itself. `intents` is **set**, not appended, on each call
— unlike `candidates` (which can accumulate across separate pipeline
stages over one message's life), one extraction call produces every intent
a message has all at once.

Added 3 tests to `test_understanding_pipeline.py`: `intents` populated
alongside (not instead of) `candidates`; the deterministic-shortcut case;
and `unknown_fields`/`missing_fields` correctly carried per-intent. Always
length 1 today — B4 is what makes it genuinely plural.

Full monorepo suite: 2698 passed (3 more — this phase's own new tests), 16
skipped (pre-existing), 230 deselected.

#### B3 — done 2026-07-31.

`build_canonical_event`'s entire body (fields construction, labour/material
normalization, occurred-date resolution, the material-direction
clarification special case, completeness/missing-fields computation) was
extracted into a new `_build_event_from_intent` helper that takes
`semantic_type`/`candidate` as explicit parameters instead of reading
`understanding.semantic_type`/re-deriving the one matching candidate via
`_select_candidate`. `build_canonical_event` itself is now a thin wrapper
calling that helper with the primary semantic_type/candidate — same
inputs, same output, verified byte-identical by the full suite before any
new behavior was added (a dedicated intermediate test run, not just the
final one).

`build_canonical_events` now branches on `len(understanding.intents)`: `> 1`
builds one event per intent directly via `_build_event_from_intent` (a new
path, only reachable once B4 ships); `<= 1` is **completely unchanged**
from before B3 — the primary event plus the existing deterministic
`work_item`-linked second segment for a material report, byte-identical.

**What the plural path deliberately does NOT yet handle, named rather than
silently absent:** entity-linking (a site's `project_id` StepRef-bound to a
project created earlier in the same message) is `planning/decomposition.py`'s
job, downstream of this function — `build_canonical_events` only builds the
per-intent `CanonicalEventV2`s here, unlinked; wiring them into a `Plan` with
`StepRef`s is unaffected by B3 and already works today for the
decompose()-based path. Whether that same linking logic needs any change
once genuinely-plural `build_canonical_events` output starts flowing into it
(B4) is not yet answered — flagged for verification when B4 lands, not
assumed safe.

Added `test_intents_plural_canonicalization.py` (4 tests, hand-constructing
multi-intent `UnderstandingResult`s directly since B4 hasn't shipped and no
real pipeline produces `len(intents) > 1` yet): the Bidilaj trace itself
(§1) — three intents in, three events out, each with its own event_type and
fields; every event sharing message-level context (organization_id/
project_id/site_id); one intent needing clarification not sinking the
others' own completeness; and an invalid `semantic_type` string on one
intent degrading only that event to `UNRECOGNIZED`, matching the
single-intent path's own existing `ValueError` handling.

Full monorepo suite: 2702 passed (4 more — this phase's own new tests), 16
skipped (pre-existing), 230 deselected.

#### B4 — done 2026-08-01. **Real-model behavior unverified from this
environment — see the VPS checklist below before trusting it in production.**

The risk step named from the start: B1–B3 built the whole plural pipeline,
but until the extraction prompt itself asks for more than one intent,
`extraction.intents` is always length 1 and none of that plumbing is
actually exercised end to end. This phase changes what the prompt asks for
and what the adapters parse back.

**Prompt change, both adapters (`platform/ai/src/mesiri_ai/adapters/
{gemini,deepseek}/adapter.py`), same diff shape in both:** the JSON envelope
at the top of `_EXTRACTION_PROMPT` changed from flat top-level
`semantic_type`/`fields`/`missing_fields`/`field_confidences` keys to a
single `"intents"` (array — one entry per DISTINCT request) key, each entry
carrying those same 4 keys. Deliberately minimal diff: the ~400-line
per-semantic-type field schema section below the envelope (labour/material/
expense/etc. field definitions) is completely untouched — verified by the
pre-existing `test_extraction_prompt_parity.py` suite passing unchanged
against the new prompt text.

**The named risk (ADR-U1):** asking for a list creates real pressure toward
over-splitting a message that is genuinely one request. Two things in the
prompt exist only to counter this, and are now tested for directly (not
just implied): an explicit statement that the overwhelming majority of
messages are one intent, with "prefer one when genuinely unsure" as the
tiebreak; and a worked example distinguishing a report that touches several
*fields* ("used 40 bags of cement for the foundation" — `work_item` is a
field of that one material_update, never a second intent) from a message
that is actually several *requests* (the Bidilaj trace).

**Parsing:** new shared `parse_extracted_intents(raw_intents: object) ->
list[ExtractedIntent]` in `platform/ai/src/mesiri_ai/models.py`, used by all
three call sites (Gemini `extract`/`understand_voice`, DeepSeek `extract`).
Lenient by design, since this reads a live model's JSON, not a trusted
internal shape: non-list or missing input returns `[]` (falls through to
`ExtractionResult`'s own B1 `_normalize`, which supplies one default
`unknown` intent — "no intents" stays unrepresentable); a non-dict entry
inside an otherwise-good list is skipped rather than failing the whole
parse (one hallucinated bad entry must not sink the real ones next to it);
`field_confidences` values are coerced to `float` (some providers may
return them as JSON ints).

**What is and is not verified.** Verified, from this environment, without
live credentials: the prompt asks for the new envelope and states the
anti-over-splitting instructions (`test_extraction_prompt_parity.py`, new
section); the parser handles the well-formed case, the Bidilaj shape, and
every malformed-input case above (`test_extraction_result.py`, new
section); both adapters correctly wire a mocked provider response of the
new shape into `ExtractionResult.intents` (`test_adapter_conversion.py`,
new section, including a full 3-intent Bidilaj-shaped mock through both
adapters). **Not verified, and not verifiable here:** whether the real
Gemini/DeepSeek models, given the changed prompt, actually return multiple
intents for a real multi-intent message, and — the riskier direction —
whether they hold the line on genuinely single-intent messages rather than
over-splitting them. No Gemini/DeepSeek credentials exist in this dev
environment; this is a live-model behavioral question, not something a
mocked-response test can answer honestly.

**What to run on the VPS to close that gap.** New file
`platform/ai/tests/test_phase_b4_live_verification.py`, marked
`@pytest.mark.provider` (defined in root `pyproject.toml`, skipped by
default — this is the first test in the repo to use that marker). It reads
credentials exactly the way the running app does
(`mesiri.bootstrap.settings.get_settings()`), so nothing new needs
configuring on a box where the app already runs — it just needs
`MESIRI_GEMINI__API_KEY` / `MESIRI_DEEPSEEK__API_KEY` to already be set,
which production requires anyway. It calls the real provider `extract()`
against:

- the Bidilaj trace itself, asserting `len(result.intents) >= 2` and that
  `project_create` is among them — the headline claim, checked against the
  real message that motivated this whole design doc;
- five deliberately single-intent messages ("used 40 bags of cement for the
  foundation", "paid 5000 for cement", "10 masons worked on the slab
  today", "JCB ran for 4 hours doing excavation", "raining since morning,
  work stopped"), each asserting `len(result.intents) == 1` — the
  over-splitting check.

Run on the VPS:

```bash
cd platform/ai
PYTHONPATH="<repo>/backend/src;<repo>/shared/contracts/src;<repo>/platform/ai/src" \
  uv run pytest -m provider tests/test_phase_b4_live_verification.py -v
```

(adjust `PYTHONPATH` separator to `:` if the VPS is Linux, not the `;` this
dev box needs on Windows). A pass on both halves is the actual, real-model
confirmation this phase's headline claim needs — until that has run once
on the VPS, treat B4 as "implemented and unit-tested" but not yet "verified
working," and do not start B5/B6 on the strength of the mocked tests alone.

Full monorepo suite (excluding the new `provider`-marked tests, which
correctly skip without credentials): 2718 passed, 16 skipped, 230
deselected, 0 failed.

### Phase C — Deferred, not in scope here

The `whatsapp_number`-arrives-later gap (§4.2) and the whole-plan permission
pre-check (`COMPOSITE_REQUEST_PLAN_LAYER.md` Phase 6, still not started, and
still a confirmed real gap in `plan_executor.py`). Both become
**single-place** fixes after Phase A, which is the main reason to do A first.

---

## 9. Amendments to `COMPOSITE_REQUEST_PLAN_LAYER.md`

Items 1 and 2 were **applied on 2026-07-31**, at the same time as this doc,
because both were statements that had become factually false — leaving them
correct-looking in the older doc is the exact drift that let the duplicate
orchestrator survive unnoticed. Items 3 and 4 are informational.

1. ~~**§14 risk table** — reopen *"Two orchestrators"*.~~ **Applied.** Row now
   reads REOPENED, with the distinction between the entity-resolution
   closure (real) and the `batch.py` duplication (never closed).
2. ~~**§9 (Decomposition)** — mark superseded.~~ **Applied.** §9 now carries a
   supersession banner; its body is kept unchanged as the record of why the
   gate was chosen, since its deferred-required-field analysis is still
   accurate and still open.
3. **§10 phases** — Phase 5 (migrate remaining entity types) and Phase 6
   (permission pre-check) survive unchanged and are unaffected by this doc.
4. **§14** — the *"single-message gates never re-run per decomposed segment"*
   row is closed by Phase A5 **structurally**, superseding the 2026-07-30
   partial closure (project/site only).

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| **Intents-plural prompt degrades single-intent accuracy** | The central risk of ADR-U1, hitting the ~95% path. §7's golden-suite gate plus the over-splitting probe fixtures (§7.4). If the gate cannot be passed, ADR-U1's rejected alternative (separate segmentation stage) is reconsidered — that is the explicit escape hatch. |
| **Golden suite is too thin to detect real degradation** | Acknowledged limit of the chosen gate (§7). Escalation path is the real-traffic replay set, deferred rather than rejected. |
| **Deleting `batch.py` loses the one working multi-segment behaviour** | ADR-U4's byte-identical reply-text anchor, verified at A2 before deletion at A6 — deletion is the *last* step, not the first. |
| **Every single-intent message pays a `PlanStore` write** | Measured at A7 and recorded. If material, the reply layer can defer persistence until `n > 1` — but that reintroduces a branch, so it needs its own decision, not a silent optimization. |
| **`UnderstandingResult` is a cross-team versioned contract (`extra: forbid`)** | B2 makes the `v1`-vs-`v2` call explicitly and updates `M2_M3_INTEGRATION_CONTRACT.md`; required reviewer per that contract's header is Alan. |
| **Concurrent sessions in this repo** | The entity-resolution layer is actively developed in parallel (`ENTITY_RESOLUTION_PLAN.md`). Phase A touches `process.py`, `dependencies.py`, `message_journey.py`, `interactions/handler.py` — all shared. Fetch before staging, stage only own files, never `git add -A`. |
| **Phase B stalls half-migrated** | The derived shims (§6.1) mean B1–B3 are independently shippable and behaviour-neutral; only B4 changes behaviour, and B5/B6 are cleanup. A stall leaves a working system with dead shims, not a broken one. |

---

## 11. Open questions

- **Does `source_span` on `ExtractedIntent` earn its place?** It would let
  the preview quote the user's own words per step ("*create a site called
  Site A*" → `Create site Site A`), which is a real UX gain for a 5-step
  plan. But it is another thing the model must get right. Decide at B4.
- **Does the over-splitting probe belong in `scenarios/` or `tests/unit/`?**
  It is a model-behaviour assertion, so it may need the `provider` marker
  and real credentials — in which case it cannot be the merge gate it is
  described as in §7.4. **Resolve before B4.**
- **What happens to `planner/ambiguity.py` when `n > 1`?** Ambiguity is
  per-intent (ADR-U3), so a 3-intent message could produce 3 independent
  ambiguity resolutions. Today's UX has no shape for that. Probably: resolve
  ambiguity per step at bind time (ADR-C2's just-in-time principle already
  applies), but this is unexamined.
- **Plan TTL** — inherited open question from the prior doc's §12, now more
  pressing since *every* message becomes a plan.

---

*Last updated: 2026-07-31 — proposed, no code written. Phase A is the next
action; it is gated on §7 items (1) and (3) only.*


---

## 12. Update 2026-10-19 — a tool-calling agent in front of the same workflows

Request [40] adds a second *front end* to this pipeline rather than another stage in it. For a
company with `assistant_mode = "agent"`, a free-text or voice message is read by a
tool-calling model (Gemini, via the platform/ai port) instead of the classify → decompose →
plan chain. Each tool builds the understanding (`Candidate`) that this document's pipeline
would have produced and feeds it to the **same** journey from context resolution on
(`runtime/agent/preset_pipeline.py` stands in for the `understand` step), so §4's stages after
understanding — canonicalization, gates, planner, workflow, save-first — are unchanged and
shared. Decision and limits: [`docs/architecture/ADR-assistant-agent-wrap-not-rebuild.md`](../architecture/ADR-assistant-agent-wrap-not-rebuild.md).

What this means for the phases above: the multi-intent decomposition (Phase A/B) still serves
every company on the classic path; on the agent path "how many things is this message?" is
answered by the model calling one tool per thing. The classic path is not deleted — "off" is
the default and the instant rollback.
