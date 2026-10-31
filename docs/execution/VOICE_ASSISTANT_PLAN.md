> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# WhatsApp Voice Assistant — Architecture Proposal & Codebase Reuse Inventory

**Status:** Proposed — not started, no code written. This is a planning document produced from an
external architecture review plus a direct read of this codebase, ahead of a Module Placement Log
entry / team decision.
**Companion doc:** "Mesiri Voice Assistant — Architecture Review" (published artifact — covers
WhatsApp Business Calling feasibility, latency budget, model selection, security, failure modes,
and a full production architecture; not duplicated here).
**Written:** 2026-07-27
**Author:** produced by an AI coding agent at the user's request; not yet reviewed by Alan/Ilan.

> **Purpose of this document.** Where the architecture review answers *"is this feasible and what
> should a production version look like in general,"* this document answers *"what in **this**
> codebase already does that job, what needs adapting, and where does new code go."* Written so a
> future session — human or AI — can pick this up without re-deriving the investigation.

---

## 1. What this is

Mesiri workers already report through WhatsApp text, voice notes, images, and documents, handled
by `apps/whatsapp-assistant/`. The proposal under review is letting workers **call** the assistant
via WhatsApp Voice Calling and get spoken answers, backed by the same structured data — not by
replaying chat history.

This document inventories what in the current codebase is directly usable for that feature, what
needs adaptation, what's genuinely new, and proposes where the new code should live given this
repo's existing module boundaries and dependency rules (`AGENTS.md`,
`apps/whatsapp-assistant/AGENTS.md`).

---

## 2. Reuse inventory

### 2.1 Identity & authorization — reusable as-is

| What | Where |
|---|---|
| `ActorReader` protocol, `ActorIdentity` | `apps/whatsapp-assistant/src/backend/ports.py` |
| `PostgresActorReader.resolve_by_whatsapp_id(wa_id)` | `apps/whatsapp-assistant/src/backend/postgres/actor.py` |

Caller identity on a WhatsApp voice call is the same Meta-verified `wa_id` used for every inbound
text/voice-note message today. Voice needs zero changes here — resolve the caller, get org/role,
gate on registration exactly as the identity gate already does in `inbound_journey.py`.

### 2.2 Read/query business logic — reusable, with one open decision (§4)

Fifteen-plus query services already exist in `apps/whatsapp-assistant/src/runtime/`:

```
labour_query_service.py       expense_query_service.py     inventory_query.py
activity_query.py             money_account_query.py       vendor_query.py
petty_cash_query.py           notification_query.py        org_settings_query.py
reversal_query.py             expense_category_query.py    duplicate_expense_query.py
escalation_query.py           evidence_query.py            material_catalog_query.py
workforce_query.py
```

`labour_query_service.py`'s own docstring: *"Answers 'how many workers today?', 'labour cost this
week', 'who worked yesterday' — the questions a supervisor asks about work already recorded."* That
is verbatim the "fast tools" tier from the architecture review (`get_workforce`, `get_material_usage`,
etc.) — already built, already pre-aggregating (not returning raw rows for an LLM to sum), already
scoped by organization/project/site server-side rather than trusted to the caller.

**Finding:** these services query Postgres directly — e.g. `LabourQueryService.__init__(self, db:
PostgresDatabase)` in `labour_query_service.py` runs its own SQLAlchemy Core query against
`labour_attendance_reports`. This is a *separate* read path from the dashboard's:
`backend/src/mesiri/domains/workforce/router.py` reads through its own repository layer
(`PostgresMaterialReadRepository`-style split, per that router's docstring). **Two parallel read
implementations of the same underlying tables already exist, for two channels.** Voice would be a
third if built the same way. This is a real decision, not a formality — see §4.

### 2.3 AI provider gateway — reusable, extend with one new port

`platform/ai/src/mesiri_ai/{ports,core,adapters}` already gives every AI capability a `Protocol`
port with a fake and a production adapter, plus shared retry/fallback/routing
(`core/{gateway,router,retry,fallback}.py`). Adapters exist for Gemini, DeepSeek, OpenAI, and
Sarvam. The closest existing precedent for a realtime voice port is
`ports/voice_extraction.py`'s `VoiceExtractionProvider` — a single call that merges transcription
and extraction (built specifically to cut a sequential STT→extract round trip, ~4.5s → one call).
Adding Gemini Live (or OpenAI Realtime) is the same shape of work: a new
`RealtimeVoiceProvider` port + one adapter, not a new architectural pattern.

### 2.4 LangGraph — the analytical pattern is reusable; the turn-state machinery is not

- **Reusable pattern:** `apps/whatsapp-assistant/src/workflows/registry.py`'s `WorkflowRegistry` /
  `WorkflowDefinition` — compile-once-cache, and the `is_informational=True` flag that exempts a
  read-only graph from the confirmation gate. Existing query graphs (`labour_query`,
  `activity_query`, `expense_query`, `account_balance_query`, `material_inventory_query`) all use
  it. A future `analyze_delay` graph (currently a stub — see below) should be built the same way:
  nodes that fetch from §2.2's services, a synthesis node, registered `is_informational=True`,
  callable with one `graph.ainvoke(state)` — from *either* channel.
- **Not reusable as-is:** `workflows/runtime.py`'s `WorkflowRuntime` — `AWAITING_CONFIRMATION` /
  `COLLECTING_FIELDS` phases persisted to Postgres via `WorkflowInstanceRepository`, the
  single-active-workflow gate, `provide_input()`/`resume()`. This exists because WhatsApp turns can
  be minutes or hours apart and must survive a process restart. A voice call's turns are seconds
  apart, held in memory for the session's lifetime. Don't force this machinery onto voice — it
  solves a problem voice doesn't have.
- **Adaptation needed:** existing query graph nodes conflate *compute* and *WhatsApp-text-render* in
  one node. `labour_query/nodes.py`'s `generate_labour_query_reply` builds an emoji-formatted string
  (`"👷 *Labour — today*"`) directly into `pending_prompt`. Voice needs the computed result split
  from its rendering so a spoken-sentence renderer can sit next to the WhatsApp-text one, both
  reading the same structured output.
- **Confirmed stub:** `workflows/ask_mesiri/` is `__init__.py` only — the open-ended "why is Block B
  delayed" capability doesn't exist for *either* channel yet. Voice doesn't inherit a free answer
  here; whoever builds it is building it for the first time.

### 2.5 Contracts-first / ports-and-adapters discipline — reusable as the working method

`shared/contracts/`, `Protocol`-based ports with fake + production adapters, dependency injection
centralized in `build_container()` — this is the house style, not optional scaffolding. A voice
channel should be built the same way from day one: contract before code, port before I/O, fake
before integration test.

### 2.6 Not reusable — genuinely new work

| Piece | Why it doesn't transfer |
|---|---|
| `NormalizedMessage.v1` | Shaped around a discrete WhatsApp message (`wa_id`, `modality`, `text`, `media`) — one request, one reply. A live call is a continuous duplex audio session, not a message. Needs its own contract (call lifecycle / session events), not an extension of this one. |
| `ingress/` → `understanding/` → `context/` → `canonicalization/` → `planner/` pipeline | Built explicitly stateless — AGENTS.md's own design principle: *"Each message is processed independently. No in-memory state is shared between invocations."* A voice session is the opposite: long-lived, stateful, full-duplex. This is the one component with no existing analog — the voice gateway / session-worker layer (see the architecture review, §10). |
| `workflows/ask_mesiri/` (delay-analysis reasoning) | Stub, not built for any channel (§2.4). |

---

## 3. Proposed placement in the current architecture

Following this repo's own convention (`apps/whatsapp-assistant/AGENTS.md` is that folder's
constitution; `backend/postgres/actor.py` is the sole SQL boundary; `runtime/` is the sole wiring
layer):

**New app: `apps/voice-assistant/`** — parallel to `apps/whatsapp-assistant/`, not nested inside it.

Why a new app and not a folder under `whatsapp-assistant/channel/`: the runtime shape is
fundamentally different (long-lived stateful session vs. stateless webhook handler), the scaling
profile is different (session-worker fleet, sticky routing, vs. horizontally-scaled stateless HTTP),
and the failure modes are different (dropped call vs. retried webhook). `channel/` today has one
job — render outbound WhatsApp messages — and forcing a live-audio session into it violates that
folder's single-responsibility rule the same way putting business validation in a LangGraph node
would.

Structure sketch, mirroring `whatsapp-assistant`'s own layout:

```
apps/voice-assistant/
├── src/
│   ├── gateway/     ← Meta Business Calling webhook: SDP offer/answer, call lifecycle.
│   │                  Mirrors ingress/verification.py's HMAC pattern for signature checks.
│   ├── session/     ← One worker per active call. Owns the realtime model connection
│   │                  (RealtimeVoiceProvider), VAD/barge-in, dialogue frame-state.
│   │                  The genuinely new runtime piece — no existing analog (§2.6).
│   ├── tools/        ← Tool Gateway. Thin adapters calling §2.2's query services (or,
│   │                  if §4 resolves that way, backend's repositories instead).
│   ├── backend/      ← Same capability-boundary pattern as whatsapp-assistant's
│   │                  backend/ports.py + postgres/actor.py.
│   └── main.py
├── tests/{unit,contract,integration}/   ← same three-tier convention as whatsapp-assistant
├── AGENTS.md         ← new constitution, same hard boundaries (no SQL outside one file,
│                        no AI SDK imports outside platform/ai, contracts-first)
└── pyproject.toml
```

Shared additions (not new apps):

- `RealtimeVoiceProvider` port in `platform/ai/ports/`, adapter in
  `platform/ai/adapters/gemini_live/` (or extend the existing `adapters/gemini/` folder — decide
  when built, following whichever precedent the DeepSeek/OpenAI adapters set for one-provider-many-
  capabilities vs. one-folder-per-capability).
- `workflows/delay_analysis/` — lives in `apps/whatsapp-assistant/src/workflows/`, registered in the
  existing `WorkflowRegistry` (§2.4), called from voice via the Tool Gateway. This is the one piece
  that's naturally shared *code*, not just a shared *pattern* — see §4 for whether that also means
  promoting it further.

---

## 4. Open decision: where should "read" logic live?

The finding in §2.2 — WhatsApp's query services and the dashboard's REST repositories are already
two independent implementations reading the same tables — isn't new to voice, but voice is the
first time a *third* consumer is on the table, which makes it worth deciding rather than repeating
the pattern by default.

**Option A — follow existing precedent.** `voice-assistant` gets its own thin read calls (either a
new query layer mirroring `runtime/*_query*.py`, or a direct cross-app call into
`whatsapp-assistant`'s existing services). Fastest to ship. Continues the existing duplication
instead of fixing it.

**Option B — consolidate now.** Promote the query logic §2.2 lists into
`backend/application/*/queries.py` (or equivalent) as the one canonical read service per domain,
called by the dashboard, WhatsApp text, and voice alike.

**Recommendation: B, at least for anything text and voice will ask identically** — workforce,
material usage, expenses, the "fast tools" tier. A numeric mismatch between what the dashboard shows
and what the voice assistant says out loud is exactly the kind of bug that erodes trust fast in a
tool people use to make site decisions. This doesn't have to happen all at once — it can land
incrementally, one domain at a time, starting with whichever fast tool ships first for voice.

This decision affects `apps/voice-assistant/src/tools/`'s shape directly and should be made once,
by whoever owns this build, before the Tool Gateway is written — not discovered halfway through.

---

## 5. Suggested build order

1. `platform/ai` — add `RealtimeVoiceProvider` port + one adapter (Gemini Live recommended in the
   architecture review — cheaper, natively multilingual, native tool calling). Small, isolated,
   testable with a fake, no dependency on anything else here.
2. `apps/voice-assistant` skeleton — webhook signature verification + SDP answer only, no AI wired
   yet. Prove a call connects and audio echoes back before any model is in the loop.
3. Wire 2–3 fast tools end-to-end through the Tool Gateway — start with labour (`labour_query_service`
   is the cleanest of the existing services to adapt first).
4. Resolve §4, then build `workflows/delay_analysis/` as the first LangGraph analytical graph,
   registered like the existing query graphs. Consider retiring the `ask_mesiri` stub for both
   channels at the same time, rather than building the same capability twice later.
5. Harden per the architecture review: dialogue frame-state, barge-in, tool-call timeouts + filler
   pattern for the analytical path, cost/latency observability, HA session-worker fleet.

---

## 6. Next steps outside this document

- This plan should get a row in the root `AGENTS.md` Module Placement Log once the team commits to
  building it. Not added here — that table is shared, team-maintained, and a placement decision
  should be confirmed by Alan/Ilan first, not asserted unilaterally by this document.
- The companion architecture review (published Artifact) covers everything this document
  deliberately doesn't repeat: WhatsApp Business Calling feasibility and economics, latency budget,
  model comparison (Gemini Live vs. OpenAI Realtime), security model, failure-mode table, and the
  full production architecture diagram.
