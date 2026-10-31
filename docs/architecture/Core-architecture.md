> **HISTORICAL.** Superseded for the WhatsApp assistant by [assistant-v2.md](assistant-v2.md) (one agent + skills + tools).
> The body below is kept as it was and describes the classic chain; do not use it as the current design.

All nine additions are documentation improvements, not architecture changes — nothing here alters a single arrow in the pipeline, it just makes the existing boundaries impossible to misread later. Worth adding all of it. Here's the complete final version, ready to paste as `docs/architecture/FROZEN_RUNTIME_ARCHITECTURE.md`.

```markdown
# Mesiri — Frozen Runtime Architecture (ADR-0)

> This document defines the canonical runtime architecture for Mesiri.
> Treat it as ADR-0. Future architectural changes must not edit this
> casually — create a new ADR (ADR-001, ADR-002, ...) explaining *why*.
> New modules must conform to this architecture rather than redefining it.

## Vision

Field teams operate entirely through WhatsApp. AI converts conversation
into structured, human-confirmed business records. Owners/managers get
real-time visibility through a dashboard built on the same event stream —
never by querying business tables directly.

## Vision

Field teams operate entirely through WhatsApp. AI converts conversation
into structured, human-confirmed business records. Owners/managers get
real-time visibility through a dashboard built on the same event stream —
never by querying business tables directly.

## Platform Overview

Mesiri is a single AI-native construction management platform.

The platform is composed of multiple runtime components that together deliver a single product experience.

### Mesiri Daily (WhatsApp Assistant)

Mesiri Daily is the AI-first interaction layer used by field teams. It is responsible for receiving WhatsApp messages, understanding user intent, resolving context, selecting workflows, orchestrating conversations, and collecting human confirmation before any business action is executed.

Responsibilities include:
- Ingress
- Understanding
- Context
- CanonicalEvent generation
- Planner
- Workflow Registry
- LangGraph Runtime

Mesiri Daily never owns business data and never writes directly to the database.

### Mesiri ERP (Business Backend)

Mesiri ERP is the business core of the platform. It owns the application layer, domain model, persistence, reporting, analytics, timeline, notifications, and all business records.

Responsibilities include:
- Application Layer
- Domain Layer
- Repositories
- PostgreSQL
- Outbox & Event Bus
- Timeline
- Analytics
- Dashboard
- Mobile APIs

Mesiri ERP is the single source of business truth.

### Relationship

Mesiri Daily and Mesiri ERP are architectural components of the same Mesiri platform, not independent products. Mesiri Daily orchestrates business operations, while Mesiri ERP executes and persists them. Together they provide a single, unified experience to end users.

## v1 scope (locked)

Four domain modules only...

## v1 scope (locked)

Four domain modules only: **Material** (arrived/used) · **Equipment &
Machinery** (on-site/usage/movement) · **Labour** (headcount/attendance)
· **Expense** (petty cash only). No approval chains, no procurement, no
full inventory, no other expense types in v1.

---

## Architecture Principles

Mesiri follows a strict layered architecture. Every layer has exactly
one responsibility. The runtime is built around contracts, ports &
adapters, dependency inversion, and event-driven communication.

- Contracts First
- Ports & Adapters
- Human-in-the-loop
- AI Orchestrates, Domain Decides
- Events are Business Truth
- Infrastructure is Replaceable
- Every Layer Has One Job
- Dependencies Always Point Downward — no layer may depend on a higher layer

---

## Canonical runtime pipeline

```

WhatsApp / Mobile / Web
↓
Ingress                    → NormalizedMessage
↓
Understanding              → UnderstandingResult
↓
Context                    → ResolvedContext
↓
CanonicalEvent             → normalized business intent
↓
Planner                    → PlannerDecision
↓
Workflow Registry          → resolves to a graph
↓
LangGraph Runtime          → runs the conversation
↓
Application Commands       → e.g. RecordMaterialReceiptCommand
↓
Application Layer          → executes the use case
↓
Domain                     → business rules, invariants
↓
Repository                 → data access
↓
PostgreSQL + Outbox        → atomic write + event
↓
Domain Events              → confirmed business facts
↓
Timeline / Analytics / Notifications / Dashboard

```

> **See ADR-002:** identity resolution runs as a lightweight pre-check before
> Understanding in the live implementation (`resolve_sender` in `dependencies.py`).

## Contract flow (what travels between layers)

```

NormalizedMessage
↓
UnderstandingResult
↓
ResolvedContext
↓
CanonicalEvent
↓
PlannerDecision
↓
ApplicationCommand
↓
DomainEvent

```

## Dependency rule

```

Ingress → Understanding → Context → Planner → Workflow Runtime
→ Application → Domain → Repository → Infrastructure

```

No layer may depend on a layer above it in this chain.

---

## Layer ownership

| Layer | Owns | Must not own |
|---|---|---|
| Ingress | Webhooks, dedup, normalize | AI reasoning, business logic |
| Understanding | STT/OCR/extraction (Sarvam, Gemini, DeepSeek) | Workflow selection, persistence |
| Context | Resolves user, org, project, site, role | Business decisions |
| CanonicalEvent | Normalizes AI output into business intent | Knowledge of AI providers, confidence scores |
| Planner | Reads CanonicalEvent, returns a `workflow_key` | Knowledge of LangGraph, knowledge of any specific graph |
| Workflow Registry | Maps `workflow_key` → graph implementation | Business decisions, conversation logic |
| LangGraph Runtime | State, transitions, pause/resume, confirmation | SQL, provider calls, domain rules, publishing Domain Events |
| Application Layer | Executes Commands, owns transaction boundary | Channel behavior, AI reasoning |
| Domain | Entities, invariants, business rules | SQL, WhatsApp, AI providers |
| Repository | Data access | Business logic |
| Database | Persistence (with outbox) | Business logic |
| Event Bus | Publishes Domain Events from the outbox | — |
| Timeline / Analytics / Notifications / Dashboard | React to Domain Events only | Direct queries against business tables |

---

## Critical terminology

**CanonicalEvent** = internal orchestration signal, not a fact yet.
Example: `MaterialReceiptRequested` means "the assistant believes the
user wants to record a material receipt." The user may still correct it,
the workflow may reject it, authorization may fail.

**DomainEvent** = confirmed business fact, published only after commit.
Example: `MaterialReceived` means it is now true and recorded.

**Commands vs Events**: Commands ask the system to perform work
(`RecordMaterialReceiptCommand`) and travel downward. Events announce
something that already happened (`MaterialReceived`) and travel outward.

Never conflate CanonicalEvent with DomainEvent.

---

## Workflow Registry

The lookup layer between Planner and LangGraph. Planner never imports
workflow implementations — it returns only a `workflow_key`. The
registry resolves that key to the correct graph:

```

material.receipt → MaterialGraph
expense.submit   → ExpenseGraph

```

This keeps Planner fully independent of workflow implementations.

## PlannerDecision shape

```

PlannerDecision
workflow_key      e.g. "material.receipt"
reason            e.g. "MaterialReceiptRequested"
priority          e.g. "NORMAL"
metadata

```

## LangGraph boundary

LangGraph owns orchestration only. It may: ask questions, pause, resume,
collect missing fields, confirm, emit Commands.

It must never: validate business rules, persist business records, call
repositories, execute SQL, publish Domain Events.

This is the single most important boundary in the architecture.

## Memory

Memory provides conversational and workflow context. Memory does not own
business truth — business truth always lives in the Domain.

---

## Outbox pattern (non-negotiable)

```

BEGIN
INSERT INTO material_receipts (...)
INSERT INTO outbox_events (...)
COMMIT

```

A separate publisher drains `outbox_events` to the event bus. Guarantees
no event is ever lost, even on a crash between write and publish.

---

## Where does new code go?

| Need | Layer |
|---|---|
| Understand language | Understanding |
| Resolve user/project/site | Context |
| Decide which workflow | Planner |
| Hold conversation state | LangGraph |
| Validate business rules | Domain |
| Access the database | Repository |
| Call an external API | Infrastructure Adapter |

---

## Non-negotiable rules

1. AI never writes directly to the database
2. Business rules execute in the Domain layer, before any commit
3. Workflows orchestrate — they never own business logic
4. Human confirmation required before persisting business-affecting data
5. Shared contracts define all cross-module communication
6. Infrastructure is hidden behind ports/adapters
7. Memory is a shared subsystem; it does not own business truth
8. Every business event is published via the outbox; none are ever lost
9. Downstream systems react to Domain Events only — never query business tables directly
10. Planner never imports a workflow engine or a specific graph
11. LangGraph never imports SQL, Postgres, or a repository

---

## Frozen runtime contracts

- `NormalizedMessage.v1`
- `UnderstandingResult.v1`
- `ResolvedContext.v2`      (v1 deprecated — see ADR-001)
- `CanonicalEvent.v2`       (v1 deprecated — see ADR-001)
- `PlannerDecision.v2`      (v1 deprecated — see ADR-001)
- `ApplicationCommand.v1`   (not yet implemented)
- `DomainEvent.v1`          (not yet implemented)

These evolve only through versioning (`.v2`, `.v3`, ...), never breaking
changes in place. Deprecated versions are documented, not silently
deleted, until confirmed unused in production.

---

## Tech stack

| Layer | Tech |
|---|---|
| Communication | WhatsApp Cloud API |
| Understanding | Sarvam AI (STT), Gemini 2.5 Pro (vision/OCR), DeepSeek (extraction) |
| Context/Memory | PostgreSQL, Redis, pgvector, Voyage AI (embeddings) |
| Workflow Runtime | LangGraph |
| Storage | PostgreSQL, Cloudflare R2 |
| Events | Redis Streams (outbox-backed) |
| Scheduler | BullMQ / cron |
| Observability | OpenTelemetry, Prometheus, Grafana |

---

## Known debt (Phase 0, resolve before Phase 1)

- ~~Retire `ContractContextResolver` + fakes; wire the real, tested `ContextResolver` and M4 schema into production~~ ✅ Done (2026-07-08) — `ContractContextResolver` deleted; `ContextResolver` with real Postgres/Redis adapters wired into `_on_normalized`
- ~~Consolidate the two `ResolvedContext` shapes into one~~ ✅ Done (2026-07-08) — `mesiri_contracts.assistant.resolved_context` is the sole canonical schema; the contract-layer duplicate is deleted
- ~~Fix `UserModel` ORM to match migrations (`status`, `access_policy`)~~ ✅ Done (2026-07-08)
- Investigate *why* two FastAPI apps duplicate auth/admin/users/projects routes before merging anything
- Wire real Cloudflare R2 in the live webhook path — the `R2ObjectStorage` adapter and `build_object_storage()` selector exist and are wired in `build_container()`; remaining work is deployment config (`MESIRI_OBJECT_STORAGE__PROVIDER=r2` + credentials) and a live verification

## Build phases

```

Phase 0 — Debt (above)
Phase 1 — Core runtime (CanonicalEvent → PlannerDecision → Workflow
Registry → LangGraph Runtime → Application Layer → Outbox)
Phase 2 — Domain modules: Material first (proof of architecture),
then Expense, Labour, Equipment
Phase 3 — Multi-tenancy hardening, observability, production readiness

```

## ADR-001: v2 contracts superseded v1 before v1 ever shipped

**Status:** Accepted

**Context:** This document originally named `ResolvedContext.v1`,
`CanonicalEvent.v1`, and `PlannerDecision.v1` as frozen. During
implementation, all three were revised to v2 shapes. The v1 classes
still exist in `shared/contracts` and are largely unused in the
runtime path (`context/service.py` retains a v1 import that should be
cleaned up in a future pass).

**Decision:** v2 is the canonical, in-use version of each contract.
v1 classes are kept as dead code for now and should be deleted in a
future cleanup pass. This document now reflects v2 as canonical.

**Consequence:** Anyone extending these contracts branches from the
v2 shape, not v1.

---

## ADR-002: Identity gate runs before Understanding

**Status:** Accepted

**Context:** The canonical pipeline as originally documented runs
Ingress → Understanding → Context. The actual runtime resolves sender
identity (`resolve_sender` in `dependencies.py`) before Understanding
executes, so unregistered senders never trigger the AI pipeline.

**Decision:** This ordering is intentional and correct — it avoids
spending AI provider calls on unauthenticated/unregistered senders.
The canonical pipeline diagram is updated to show identity resolution
as a lightweight pre-check before Understanding, distinct from the
full Context resolution step that still happens after Understanding.

**Consequence:** Future contributors should not "fix" this back to the
original documented order.

---

## ADR-003: LangGraph runs without a checkpointer in v1

**Status:** Accepted (revisit in Phase 3)

**Context:** The architecture states LangGraph owns state, transitions,
and pause/resume. The current Material graph is compiled without a
checkpointer and runs start-to-end in a single invocation
(`build_draft` → `request_confirmation`). All state durability is
handled by `PostgresWorkflowInstanceRepository` outside LangGraph.

**Decision:** Acceptable for v1 because Material's confirmation flow
is single-turn (confirm/reject only, no mid-graph clarification
questions). Do not add a checkpointer until a workflow genuinely
requires multi-turn, mid-graph state.

**Consequence:** Any future workflow needing branching or follow-up
questions mid-conversation will need a checkpointer added at that
point — flag this explicitly when designing Equipment, Labour, or
Expense if they need that pattern.

---

## Change policy

Do not modify this architecture while implementing Material unless you
hit a real, demonstrated limitation. Material is the proof this
architecture works end to end. Future changes go through a new ADR, not
an edit to this file.
```