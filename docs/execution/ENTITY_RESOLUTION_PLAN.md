> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Entity Resolution & Workflow Chaining

> **Status:** proposed (design only — no code written)
> **Author:** drafted 2026-07-30
> **Module Placement Log row:** see `AGENTS.md`

---

## 1. The problem, stated by a real message

A project manager sent, in Malayalam:

> ഹോസ്പിറ്റൽ പ്രോജക്റ്റിലെ ഹൈസം എന്നുള്ള ഒരു പ്രൊജക്ട് മാനേജർ ആയിട്ട് ഒന്ന് ആഡ് ആക്കൂ
> *("add Hysam to the hospital project as a project manager")*

They confirmed the draft with **Yes**, and got:

```
⚠️ Couldn't record this: couldn't find an active user named Hysam
```

Three separate failures are visible in that one reply:

1. **It is a dead end.** The assistant knows a user is missing and knows how to
   create one (`WorkflowKey.CREATE_USER` shipped the same day), but the two
   facts never meet.
2. **It fails *after* confirmation.** The name is resolved at execution time
   (`application/projects/handlers.py:173`), so the user confirms a draft that
   was never capable of succeeding. "Yes" → "actually, no."
3. **It can never succeed by retrying.** `find_by_full_name_active`
   (`repositories/users.py:42`) is a case-insensitive *exact* match. ഹൈസം
   transliterates as Hysam / Hisham / Haisam / Haitham. If the person exists as
   "Hisham", every retry fails identically, forever.

The obvious fix — "if the user is missing, offer to create one" — is a fourth
bug waiting to happen. It hard-codes one pair of workflows and does nothing for
the next pair.

---

## 2. Why this is not one bug

The same shape — *resolve a named thing; it isn't there; now what?* — is
implemented independently across the codebase:

| Layer | Count | Examples |
|---|---|---|
| Backend resolvers | ~8 modules | `materials/resolution.py`, `expenses/resolution.py`, `finance/resolution.py`, `finance/petty_cash_resolution.py`, `automations/name_resolution.py`, `projects/name_resolution.py`, `progress/resolution.py` |
| Assistant gates | 4 | `_run_material_unit_gates`, `_run_project_gate`, `_run_site_gate`, `_run_stock_gate` |
| Hold/resume paths | 7 | `resume_pending_report_with_{project,material,unit,site,material_create,material_unit_choice,stock_choice}` |
| Seed functions | 15 | `_seed_account_candidates`, `_seed_petty_cash_recipient`, `_seed_worker_candidates`, … |

**The duplication is already documented in the code itself.** Read the module
docstrings in order:

- `projects/name_resolution.py` — *"mirroring `application/automations/name_resolution.py`'s AudienceNameResolver shape almost exactly"*
- `automations/name_resolution.py` — *"mirroring `application/finance/resolution.py`'s AccountLookupResolver shape and reusing the exact lookup"*
- `finance/resolution.py` — *"mirrors `application/expenses/resolution.py`"*
- `expenses/resolution.py` — *"mirrors `application/materials/resolution.py`"*
- `progress/resolution.py` — *"mirroring `application/materials/resolution.py`"*

A copy-chain five deep, each link acknowledged in writing. Nobody did anything
wrong; there was simply never a shared abstraction to reach for, so each new
entity type honestly copied the nearest neighbour.

### 2.1 The good behaviour already exists — once

Materials are the exception. An unknown material on a usage report does **not**
hard-reject; it offers to create the material and then *resumes the original
report* (`resume_pending_report_with_material_create`). "50 bags cement for slab
work" already works the way the whole product should.

Every other entity type hard-rejects instead — and
`application/finance/resolution.py` elevates that to a stated principle:
*"hard rejection, never a silent default."*

That principle is right about **never silently guessing** and wrong about
**stopping there**. Refusing to invent a value is correct. Refusing to offer the
user a way forward is what makes the assistant feel like a bot.

**The design goal of this plan is to make the material behaviour the default for
every entity type, rather than a special case someone wrote once.**

---

## 3. Design

Three pieces. The third is what distinguishes this from an `if/else`.

### 3.1 One resolution outcome

Every "find the thing the user named" becomes one call with three outcomes:

```
resolve(entity_type, name_hint, scope) →
    Resolved(id)             → carry on, unchanged
    Ambiguous([candidates])  → picker: "Did you mean Hisham?"
    Missing                  → this thing does not exist yet
```

`Ambiguous` is where the transliteration problem is solved — **once**, for every
entity type, instead of eight times. ഹൈസം → Hysam is a near-miss on Hisham, not
an absence. Prior art to lift: `domains/workforce/matching.py`'s `match_worker`,
already doing fuzzy person-matching for labour attendance.

### 3.2 The registry declares the graph

`workflows/registry.py` is already the single source of truth for workflow
metadata (it gained the user-facing copy fields on 2026-07-30). Two more
declarations:

```python
provides: frozenset[EntityType]   # CREATE_USER          -> {USER}
requires: frozenset[EntityType]   # ADD_PROJECT_MEMBER   -> {USER, PROJECT}
```

Both are `frozenset`, matching `allowed_roles: frozenset[str]` on the same
dataclass. `provides` is a set rather than a single value even though every
workflow today provides at most one entity — a workflow that creates a user
*and* their petty-cash account is plausible, and widening a field later is more
disruptive than starting wide.

These two fields are shared with the Composite Request Plan layer, which reads
the same table forwards while this layer reads it backwards (see §8).

Then *"a USER is missing — what now?"* is a **lookup**, not a branch:

```python
provider = workflow_that_provides(EntityType.USER)   # → CREATE_USER
```

This is the whole point. No module contains the sentence "if the user is
missing, run create-user." A new entity type declares itself and is wired in;
nothing else changes. Workflows come to know about each other through the
registry rather than through hand-written pairings.

### 3.3 One hold-and-resume continuation

> Workflow **W** blocked needing entity **E** → run the workflow that provides
> **E** → substitute the new id → **resume W where it left off.**

This is what stops it feeling like a bot. Not "✅ user created" followed by the
user retyping their original request — it finishes the job they actually asked
for:

```
"add Hysam to the hospital project as PM"
  → USER "Hysam" unresolved; nearest active user is "Hisham"
  → "Did you mean Hisham?"  [Hisham] [Someone else]
  → [Someone else] → "Create a new user, Hysam?"  [Yes] [Skip]
  → [Yes] → "What's their WhatsApp number?" → 9198765xxxxx → created
  → …and Hysam is added to the hospital project as PM. Done.
```

**Most of the substrate already exists.** `PendingReportStore` proves the
pattern (hold a `CanonicalEventV2` per user, pop-once, 10-minute TTL) and
`_plan_and_run` is already shared by all seven resume functions — so the resume
path is not new work, only the storage is.

The storage is a `Plan` of size 1 in the shared `PlanStore`, **not** a
generalised `PendingReportStore`: a single-slot store cannot express the
multi-step case, and building one would force a second orchestrator. See §8.1,
which settles this with the composite-request layer. A missing entity *inserts a
step*; it does not invent its own suspend mechanism.

Behaviourally this reproduces `resume_pending_report_with_material_create`
exactly, minus the hard-coding of "material" — which is what Phase 3 exists to
verify.

---

## 4. Decisions

**ADR-E1 — Resolution moves before the draft, not after.**
Today the name is resolved at execution time, so the user confirms a doomed
draft. Resolution belongs in the gate phase, before a confirmation prompt is
ever shown. Workflow nodes cannot do I/O (`workflows/runtime.py`), so this runs
as a seeding/gate step, the same place the material and project gates already
run.

**ADR-E2 — Backend resolvers stay as defence in depth.**
This plan does not delete the backend `*resolution.py` modules. They are
explicitly documented as defence-in-depth guards for the REST path, which has no
assistant gate in front of it. They stop being the *primary* mechanism for chat,
and their rejection messages stop being user-facing copy — but a command that
reaches a Handler unresolved must still be rejected, not silently defaulted.

**ADR-E3 — Depth 1 is a policy limit, not a storage shape.** *(revised — see §8.1)*
V1 resolves one missing entity per request; a second missing prerequisite inside
the provider workflow is a plain error. Revisit only with a real case.

The first draft of this ADR made that limit *structural*, by generalising
`PendingReportStore` (one held event per user). That was wrong.
`COMPOSITE_REQUEST_PLAN_LAYER.md` §4.4 correctly points out that a depth-1 pause
is a plan of size 1, but a plan of size N is **not** reducible to a depth-1
pause — so building this layer on a single-slot store would force that layer
onto a second store, producing exactly the two orchestrators both documents
exist to prevent.

**Resolved:** this layer's continuation is a `Plan` of size 1, stored in the
shared `PlanStore` (that doc's §6). A missing entity **inserts a step** into the
plan rather than suspending it through a separate mechanism. Depth 1 survives as
a constraint on *what this layer may insert*, enforced in code, not as a
property baked into storage.

**ADR-E4 — `Missing` always offers, never auto-creates.**
The offer is tappable Yes/Skip, never implicit. Creating a user, a vendor, or a
money account is a real write with real consequences (a new user gets WhatsApp
access to org data). "Never a silent default" from
`application/finance/resolution.py` is preserved exactly — what changes is that
the alternative to a silent default becomes an offer rather than a dead end.

**ADR-E5 — Role gates apply to the provider, not just the original.**
A SITE_ENGINEER who triggers a `Missing USER` must not be offered CREATE_USER,
because `_PROJECT_CREATE_ROLES` will refuse them. The offer is filtered by
`WorkflowDefinition.allowed_roles` (added 2026-07-30) — the same field the
capability menu and help matcher already filter on. They get the plain "not
found" reply, plus who to ask.

**ADR-E6 — Reuse `ProjectSetupOfferStore`'s shape, not the store itself.**
The project→site→member chain already implements "offer the next step as
tappable buttons, remember what it was about, expire after 10 minutes." That
shape is right and should be generalised; whether it becomes one store or two is
an implementation detail for Phase 1.

---

## 5. Sequencing

A strangler, not a big-bang rewrite. Each phase leaves the system working.

| Phase | Work | Proves |
|---|---|---|
| **0** | This document; Module Placement Log row | Shape agreed before code |
| **1** | `EntityType`, resolution outcome, registry `provides`/`requires`, and the shared **N-capable `PlanStore`** (see §8.1) | The mechanism exists, and there is only one of it |
| **2** | Migrate **USER** onto it (the live Hysam bug), including `Ambiguous` fuzzy matching | End-to-end on a real failure |
| **3** | Migrate **MATERIAL** | The strongest correctness check — the generic path must reproduce `resume_pending_report_with_material_create` exactly. If it can't, the design is wrong |
| **4** | ~~Migrate ACCOUNT, VENDOR, AUDIENCE, PROJECT, SITE~~ → **done as VENDOR, petty-cash recipient, AUDIENCE**; ACCOUNT/PROJECT/SITE struck as not name-resolution at all (§5.2–5.3) | The duplicates collapse — and turn out to be fewer, but realer, than counted |

Phases 1–2 fix the reported bug. Phases 3–4 are where the duplication actually
dies. **Phase 3 is the honest test of this plan** — materials are the one entity
whose good behaviour already exists, so if the generic mechanism cannot express
it without special-casing, the abstraction is wrong and should be reconsidered
rather than forced.

> **Status: all phases shipped, 2026-07-30.** The abstraction held. Results
> and corrections are recorded in §5.1–5.4 below — including two defects the
> migrations found in already-shipped machinery, and three entities struck
> from Phase 4 as not being resolution problems at all.

### 5.1 Phase 3 result (shipped 2026-07-30)

**Verdict: the abstraction holds, but it is two things, not one.** Materials
migrated onto the shared vocabulary with no special-casing and no behaviour
change — all 39 existing material gate/resume tests passed untouched, which is
the correctness check this phase was defined to be. Two findings, both recorded
in `runtime/entity_resolution/material_resolution.py`'s module docstring:

**Finding 1 — the layer splits into a matching half and a vocabulary half, and
each entity needs only what it needs.** `member_resolution.py` supplies both to
USER: difflib near-match scoring *and* `Resolved`/`Ambiguous`/`Missing`.
Materials need only the vocabulary — their matching already happens in SQL
(`find_by_name_exact_active`, then `find_by_name_fuzzy`'s substring/ILIKE) and
substring is genuinely the better technique for a curated catalog: "cement"
must match "OPC Cement 53 Grade", which difflib scores at 0.35 and would throw
away. Phase 3 therefore did **not** re-implement scoring for materials. This is
the abstraction being honest, not a gap in it — and it is the shape Phase 4
should expect, since ACCOUNT/VENDOR are catalog-like (SQL matching) while
AUDIENCE is person-like (scoring).

**Finding 2 — MATERIAL deliberately gets no `EntityType` member.** `EntityType`
answers "which workflow provides a missing X?", and *no workflow provides
MATERIAL*: a catalog entry is created by a direct `create_material` write inside
`_create_material_and_resume`, not by a confirmed workflow the way CREATE_USER
is. Adding the member would make `workflow_that_provides(MATERIAL)` return
`None` — a lie in the one table whose entire purpose is answering that question.
So §3's chaining half (insert a step → run the provider workflow → resume) does
not apply to materials at all, and the create-offer/resume legs in `resume.py`
are untouched. **Phase 4 should check this per entity before assuming a
provider exists.**

**One tension found, then closed (follow-up commit).** The migration surfaced
that a *single* substring match auto-resolved silently, contradicting
`find_by_name_fuzzy`'s own docstring ("candidates for a WhatsApp
disambiguation picker, never auto-accepted"). It was left alone in the
migration commit itself — a migration should not change behaviour — and pinned
by a test written to fail loudly the moment anyone tightened it. That pin then
did its job.

It is now closed: **only an exact name match resolves silently**, decided in
`classify_material_matches` by comparing the hint against the row's own name
(via the package's shared `normalize_name`, the same rule `member_resolution`
uses), because `find_materials` flattens the exact and substring probes into
one list and by that point a lone exact hit and a lone substring hit are
indistinguishable by shape.

Closing it required a second change to be safe, and this is the part worth
remembering: **`render_material_picker` had no escape hatch.** The member
picker has always offered "Someone else"; the material picker offered only its
candidate rows. Making a lone substring candidate `Ambiguous` without fixing
that would have produced a one-row picker whose only tappable option was the
wrong material — strictly worse than the silent resolve it replaced, since the
old path at least let the user decline at the confirmation prompt. The picker
now always appends a "None of these" row
(`MATERIAL_CANDIDATE_NONE_ROW_ID`), which falls through to the same
create-offer / not-found handling a `Missing` result would show, gated by the
same org setting.

Worth generalising in Phase 4: **an `Ambiguous` that cannot be declined is not
a question, it is a trap.** Any entity migrated onto this layer needs its
picker checked for an escape before its matching is tightened.

### 5.2 Phase 4 — VENDOR shipped, and the entity list corrected

**VENDOR is migrated** (the one entity in Phase 4's list with a live defect).
`VendorQueryService.exists()` was exact-match only, and
`application/vendors/resolution.py` creates a brand-new vendor row for any
`vendor_text` its own exact match misses. So "Sharma Traders" at an org that
already had "Sharma Trading Co" asked *"add it as a new vendor?"* and, on Yes,
wrote a **second row for the same business** — §1's Hysam bug with a vendor
instead of a person, and worse in one respect: it compounds silently, because
every alternate spelling becomes another row and the org's spend splits across
them with nothing ever looking wrong.

Now: `resolve()` on the shared vocabulary. `Resolved` rewrites `vendor` to the
stored spelling (the backend re-matches on exactly that string, so this is what
prevents the duplicate); `Ambiguous` seeds `vendor_candidates` so
`resolve_vendor` offers the near-matches *ahead of* "add new" and "skip" —
which are the escape rows §5.1 says an Ambiguous must always have; `Missing`
keeps the original offer unchanged.

Vendors use the **person-like** matcher, not materials' SQL substring: a
business name is a free-hand rendering of something heard, so "Sharma
Traders"/"Sharma Trading Co" must meet, and substring can never connect them
(neither contains the other). That made VENDOR the scorer's second caller, so
`resolve_name_hint`/`NamedCandidate` moved out of `member_resolution.py` into
`name_matching.py` — nothing about them was ever user-specific.

**The correction: Phase 4's list of five is really two.** Reading the actual
resolvers rather than their filenames:

| Listed | What it actually is |
|---|---|
| **VENDOR** | A real distinct entity, real defect. **Shipped.** |
| **AUDIENCE** | `automations/name_resolution.py` resolves `audience_names` → **user ids** via `find_by_full_name_active`. This is USER resolution in batch. |
| **PROJECT** | `projects/name_resolution.py` resolves `member_name` → **user ids** via the same call. Also USER resolution — already fixed assistant-side in Phase 2. Project *selection* is an auth-scoped picker over `actor.projects` with no free-text hint, so it is not a resolution problem at all. |
| **SITE** | As PROJECT — `_run_site_gate` is an auth-scoped picker, no name hint. |
| **ACCOUNT** | `_seed_account_candidates` seeds the whole account list and `resolve_account` matches the user's *answer* against it. A picker, not a name→row lookup. Nothing broken. |

So the duplication §2 counted is narrower and sharper than it looked:
`automations/name_resolution.py`, `projects/name_resolution.py`, and
`finance/petty_cash_resolution.py` are **one entity (USER) resolved three
times through the identical exact-match `find_by_full_name_active`** — not
three entity types. Two of those three still exact-match and hard-reject
today: an automation audience ("ask Ilan or Hysam") and a petty-cash
recipient both fail on exactly the transliteration §1 opens with.

### 5.3 Phase 4 complete — and one correction to "one shared fix"

**Shipped: VENDOR, petty-cash recipient, AUDIENCE.** All three now resolve
before a draft exists, on the shared vocabulary, each with a picker carrying
the escape row §5.1 requires.

**ACCOUNT, PROJECT and SITE are struck from the plan, not deferred.** Per the
table above none of them is a name→row lookup: ACCOUNT is a picker over
seeded candidates, PROJECT/SITE are auth-scoped pickers with no free-text
hint. Writing code to satisfy that row would be work done to make this
document look finished. **Phase 4 is closed.**

**A correction to §5.2's own recommendation.** That section proposed AUDIENCE
and petty-cash as "one shared fix". They share a *resolver* but not a
*shape*, and the difference decided both implementations:

- **Petty cash** could not use the cheap in-graph slot mechanism VENDOR used.
  After the user taps a name, resolving that person's *advance account* is a
  DB round trip, and a node may never do I/O — so it needed the full
  gate + picker + resume-leg shape. The resume leg resolves the account
  itself, since `_plan_and_run` does not re-run the seeding pass. That
  ordering is the point: the account is created only for the person actually
  chosen. Resolving candidates up front would have been simpler and would
  have created advance accounts for people nobody picked.
- **AUDIENCE** is N names, not one. It resolves in order and stops at the
  first unsettled name, asking about that one alone; answering re-enters the
  gate. The loop lives in the gate, so three unknown names is that leg three
  times with no special handling.

Both `Missing` cases deliberately **stop** rather than continuing without the
person, and neither offers to create the user the way the member gate's
`Missing` does. Issuing cash is a poor moment to also be creating the payee —
the new user would immediately be the destination of a money movement — and
an automation that silently drops a name fails precisely when it was meant to
help, with nobody finding out until the reminder never arrived.

### 5.4 The threshold bug Phase 4 surfaced

Building AUDIENCE turned up a defect in the *shared* scorer, found because a
test used a realistic roster rather than a convenient one:

> `"Ilan"` against an org holding **"Ilan Usman"** scored **0.571** — under
> `_ASK_THRESHOLD` — and returned `Missing`: *"I couldn't find Ilan"*, about
> someone plainly in the org.

The failure mode is worse than the miss itself: whether a first name worked
depended on **how long the surname happened to be**. `"Rajesh"`/`"Rajesh
Kumar"` scores 0.667 and worked; `"Ilan"`/`"Ilan Usman"` did not. Nothing
about that is predictable or workable-around, and people refer to each other
by first name constantly — so this was live for members and petty-cash
recipients too, not only automations.

**Fix:** a hint matching a *whole word* of a candidate's name is always
offered, regardless of ratio. Deliberately a candidate signal only, never a
resolve — an org can hold two people sharing a first name, so it still ends
in the picker the caller was going to show anyway. Whole words only, so
`"an"` cannot match `"Anand"`. Pinned by
`test_audience_name_gate.py::test_a_bare_first_name_is_offered_rather_than_declared_missing`.

This is the second time a Phase-4 entity exposed a flaw in machinery Phase 2
had already shipped and tested (§5.2's `find_by_name_fuzzy` tension was the
first). Migrating a new entity onto shared code is, in practice, the most
effective review that code gets.

---

## 6. Non-goals

- **Not** a rewrite of the workflow engine, the planner, or LangGraph usage.
- **Not** a change to what any workflow *does* once its entities resolve.
- **Not** auto-creation of anything (ADR-E4).
- **Not** multi-level chaining (ADR-E3).
- **Not** a replacement for backend validation (ADR-E2).

---

## 7. Open questions

1. **Fuzzy threshold.** How close is "did you mean"? Too loose suggests
   strangers; too tight and ഹൈസം never finds Hisham. Needs real org data —
   `match_worker`'s existing threshold is the starting point, not the answer.

   **Measured against the shipped `_ASK_THRESHOLD = 0.6`** (difflib ratio on
   normalized names), using §1's own list of plausible readings of ഹൈസം:

   | Pair | Ratio | At 0.6 |
   |---|---|---|
   | Hysam / Hisham | 0.727 | offered ✅ (the live bug) |
   | Hysam / Haisam | 0.727 | offered |
   | Hysam / Hysamm | 0.909 | offered |
   | **Hysam / Haitham** | **0.500** | **missed ❌** |
   | Sunil / Sunita | 0.727 | offered (correctly asks) |
   | Ramesh / Rakesh | 0.833 | offered (correctly asks) |

   The bug that motivated this plan is fixed, but **§1's own example set
   already contains a miss**: if the real person is stored as "Haitham", the
   near-match does not reach them.

   The consequence is asymmetric and worth stating plainly. A *false
   positive* is cheap — it becomes one extra row in a picker a human is
   already reading, which is exactly the safety argument in
   `member_resolution.py`'s docstring. A *false negative* is not: it does
   not degrade to "not found", it degrades to `Missing` → "create a new
   user?" → **a duplicate person with their own WhatsApp access**, while the
   original account still exists. So the tuning pressure runs toward loose,
   not tight, and the two directions must not be traded off as if
   symmetric.

   This is also the strongest argument for open question 2 below: 0.500 is
   a Latin-transliteration artifact, and the Malayalam original may score
   these pairs far better.
2. **Cross-script matching.** Does the near-match run on the Malayalam original,
   the transliteration, or both? Extraction gives us the translated text; the
   original script may be the better signal for a person's name.
3. ~~**Does `EntityType` belong in `shared/contracts`?**~~ **Closed** — see
   §8.3. Registry-local, following `WorkflowCategory`'s precedent. Revisit only
   if a backend resolver ever keys off it directly.
4. **Idempotency across the resume.** The original event carries an idempotency
   key generated before the pause. Confirm it survives the create-and-resume trip
   without either replaying or duplicating.

---

## 8. Relationship to the Composite Request Plan layer

[`COMPOSITE_REQUEST_PLAN_LAYER.md`](COMPOSITE_REQUEST_PLAN_LAYER.md) (Ilan,
same day) covers the *other* half of the same problem: one message stating
several intents up front ("create project Paraclette, then site Tower B, add
Hysamm as PM, and log slab work started"), rather than one intent discovering a
missing prerequisite mid-flight.

The two were designed independently and converged on the same registry
declaration (§3.2). That document defers field ownership to whichever design
lands first; this one landed first, so the `frozenset` shapes above are
canonical — a shape adopted *from* that doc, since it was the better of the two.

**Adopted from that document verbatim, because it is correct and this plan is
incomplete without it:**

> There is one plan object and one executor. Decomposition inserts steps into it
> before execution; entity resolution inserts steps into it during execution. A
> missing entity is a step insertion, not a separate suspend mechanism.

Without that invariant the two layers would produce two dependency sequencers,
two Redis state stores, two confirmation UXes, and no defined answer to "what
happens when a planned step hits a missing entity."

**Consequence for build order:** this layer's generic continuation (§3.3) *is*
that layer's executor — discovered late instead of early. So this one is built
first, and composite decomposition becomes a second producer of steps into
machinery that already exists. Building it the other way round would mean
constructing plan sequencing on top of the ten independent resolvers this plan
is collapsing.

### 8.1 §4.4 settled — one store, built here

That document asks for one item to be settled in writing here before either side
writes code. **Agreed, as proposed, with one amendment.**

*Agreed:* this layer does not generalise `PendingReportStore`. It uses the
shared `Plan`/`PlanStep`/`PlanStore` contracts (that doc's §6) with a plan of
size 1. A missing entity is a step insertion. ADR-E3 above is revised
accordingly.

*Amendment — who builds it:* that doc's own build-order finding is that this
layer's continuation **is** its executor, so this layer goes first. It follows
that **Phase 1 here builds `PlanStore` N-capable from the start**, rather than
waiting on that layer's Phase 1 or shipping a size-1-only store to be widened
later. Retrofitting N onto a single-slot store is precisely the drift both
documents are written against.

So: this layer builds the store and is its first consumer, only ever inserting
plans of size 1. Composite decomposition becomes a **second producer** into
machinery that already exists and is already proven by Phases 2–3.

Net effect on this plan: Phase 1 grows (design `PlanStore` for N, not just
generalise a Redis key). Phases 2–4 are unchanged. The Hysam fix still lands in
Phase 2.

### 8.2 Objection — `allowed_roles` must not become load-bearing

That doc's §4.3 and ADR-C5 propose promoting `allowed_roles` from advisory to a
hard, plan-wide permission check. **This layer objects, and the objection is
about safety rather than scope.**

The field was added on 2026-07-30 as *discovery metadata only*, and its comment
in `registry.py` states the property that makes it safe to keep as a mirror:

> If it drifts, a menu row is wrong; nothing becomes permitted that was not
> already permitted.

It mirrors gate constants that `process.py:96` documents as **deliberately kept
as independent literals per entry point**. A mirror is safe *because* it is
advisory. Promote it to enforcing and that property inverts: a drifted mirror
becomes a privilege bug, and the real gates and the mirror must now be kept in
lockstep forever — with nothing in the type system to enforce it.

The underlying need is legitimate: a five-step plan must not stop halfway
through something the user already approved. **The fix is to check the plan
against the real gates, not against the mirror** — call the actual gate
predicates (`process.py`'s `_ACCOUNT_ADMIN_ROLES` / `_PROJECT_CREATE_ROLES`
checks and their `application/*/validation.py` counterparts) for each step
before the preview. Same user-visible behaviour, no new governance surface, and
the mirror stays advisory.

If plan-wide gating genuinely needs one callable predicate, the right move is to
extract one from the existing gates and have *both* the gates and the plan check
call it — not to elevate a field whose stated contract is that it is never
load-bearing.

### 8.3 Accepted from that document

- **`EntityType` location** (open question 3, now closed): registry-local, not
  `shared/contracts` — consistent with `WorkflowCategory`'s own precedent.
  `workflows/entities.py` if the enum outgrows `registry.py`.
- **`provides`/`requires` as `frozenset`** — already adopted in §3.2.
- **ADR-C2 (just-in-time canonicalization)** applies to any step this layer
  inserts, for the same reason: a newly created user's id cannot exist in a
  `CanonicalEventV2` built before the creating step ran.

---

## 9. Verification

This plan is written against a bug found by sending real WhatsApp messages, and
must be verified the same way. Unit tests can prove the continuation resumes;
only a live Malayalam message can prove ഹൈസം reaches Hisham.

Every phase needs a live send before it is called done.
