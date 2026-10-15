# WhatsApp Assistant — Engineering Constitution

> **You are an AI coding agent about to work in `apps/whatsapp-assistant/`.**  
> Read this entire document before writing a single line of code.  
> Every rule here is derived from the current implementation — not from plans.  
> Violating these rules creates entanglement that is very difficult to unpick.

---

## Table of Contents

1. [What This Folder Owns](#1-what-this-folder-owns)
2. [What This Folder Must NOT Do](#2-what-this-folder-must-not-do)
3. [Folder Structure and Module Responsibilities](#3-folder-structure-and-module-responsibilities)
4. [Runtime Architecture](#4-runtime-architecture)
5. [Runtime Journey — Step by Step](#5-runtime-journey--step-by-step)
6. [Current Implementation Status](#6-current-implementation-status)
7. [Contracts](#7-contracts)
8. [Ports and Adapters](#8-ports-and-adapters)
9. [Dependency Rules](#9-dependency-rules)
10. [Design Principles](#10-design-principles)
11. [Common Mistakes](#11-common-mistakes)
12. [Development Checklist](#12-development-checklist)
13. [Glossary](#13-glossary)

---

## 1. What This Folder Owns

This folder is the **AI conversation layer** of Mesiri. It owns everything from WhatsApp webhook reception to WhatsApp reply.

| Responsibility | Status |
|---|---|
| WhatsApp webhook reception and signature verification | ✅ |
| Message deduplication (24-hour TTL) | ✅ |
| Raw Meta payload normalization → `NormalizedMessage.v1` | ✅ |
| Media download from Meta CDN | ✅ |
| Media upload to object storage | ✅ (R2 adapter exists; `FakeObjectStorage` used unless `MESIRI_OBJECT_STORAGE__PROVIDER=r2` is configured) |
| Identity gate — blocks unregistered / no-org / suspended users | ✅ |
| Speech-to-text orchestration (Sarvam) | ✅ |
| Vision / OCR orchestration (Gemini) | ✅ |
| Structured field extraction (Gemini / DeepSeek) | ✅ |
| Confidence scoring (deterministic policy) | ✅ |
| Context resolution — who/org/project/site/role | ✅ wired (~90%) |
| Canonicalization — normalizes AI output into business intent | ✅ |
| Planner — routes to the correct workflow | ✅ (not yet consumed downstream) |
| Workflow runtime — LangGraph state machines | 🔲 stub only |
| Human-in-the-loop interaction layer (M7) | 🔲 stub only |
| Application & Domain Execution (M8) | 🔲 not started |
| Conversation memory (M19) | 🔲 stub only |
| WhatsApp reply rendering | ✅ (M3-based only) |
| HTTP control-plane APIs (auth, users, projects, admin) | ✅ |

This folder does **not** own:

- The PostgreSQL schema (tables, Alembic migrations) — owned by `backend/`
- The backend REST API — owned by `backend/`
- The mobile application — owned by `apps/mobile/`
- AI provider SDKs and gateway logic — owned by `platform/ai/`
- Shared data contracts — owned by `shared/contracts/`

---

## 2. What This Folder Must NOT Do

These are **hard boundaries**. Each one has a code example showing the wrong and correct pattern.

---

### MUST NOT: Write SQL anywhere except `backend/postgres/actor.py`

```python
# WRONG — SQL anywhere in whatsapp-assistant/src
from sqlalchemy import text
result = await conn.execute(
    text("SELECT * FROM users WHERE whatsapp_number = :wa_id"), {"wa_id": wa_id}
)

# CORRECT — read through the ActorReader port
actor = await actor_reader.resolve_by_whatsapp_id(wa_id)
```

`backend/postgres/actor.py` is the **only file** in this folder permitted to write SQL, hold a SQLAlchemy engine, or know any table name. If the schema changes, only that file changes. The rest of the assistant is untouched.

---

### MUST NOT: Import SQLAlchemy, ORM models, or bcrypt outside `backend/postgres/`

```python
# WRONG
from mesiri.infrastructure.postgres.models.user import User
from sqlalchemy.orm import Session

# CORRECT
from backend.ports import ActorIdentity
```

ORM models carry schema knowledge — column names, relationships, types. The assistant must not know about table structure.

---

### MUST NOT: Define shared contracts inside this folder

```python
# WRONG — apps/whatsapp-assistant/src/my_module/events.py
class ReceiptCreatedEvent(BaseModel):
    receipt_id: str

# CORRECT — shared/contracts/src/mesiri_contracts/events/receipt.py
class ReceiptCreatedEvent(BaseModel):
    receipt_id: str
```

A contract defined inside the assistant can only be consumed by the assistant. That is an internal data class, not a contract. Real contracts live in `shared/contracts/` so both the producer and consumer import from the same canonical location.

---

### MUST NOT: Call AI provider SDKs directly

```python
# WRONG — anywhere in this folder
import google.generativeai as genai
model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content("classify this")

# CORRECT — use the port
result = await self._extraction.extract(text, correlation_id=correlation_id)
```

All SDK imports, retry logic, model selection, fallback, and credential management live in `platform/ai/`. The assistant imports only from `mesiri_ai.ports.*`. Calling SDKs directly bypasses retry/fallback, couples the assistant to a vendor, and requires live API keys in tests.

---

### MUST NOT: Persist business records

```python
# WRONG — creating a record inside the assistant
await db.execute("INSERT INTO material_receipts ...")

# CORRECT — call the application layer (M8)
await material_service.record_receipt(command)
```

The assistant collects and routes. It never stores domain data. Business records belong to the domain service layer in the backend.

---

### MUST NOT: Put business validation rules in LangGraph nodes

```python
# WRONG — business rule inside a workflow node
def validate_quantity(state):
    if state["quantity"] <= 0:
        raise ValueError("Invalid quantity")

# CORRECT — validation happens in the domain service
await material_service.record_receipt(CreateReceiptCommand(...))
# The service raises a domain exception; the workflow catches and routes
```

Business rules change with the business. Rules in workflow nodes require code deployments to change. Domain services are the single source of truth for rules.

---

### MUST NOT: Generate a new `correlation_id` mid-journey

```python
# WRONG — minting a new correlation ID in any handler
import uuid
correlation_id = str(uuid.uuid4())

# CORRECT — propagate the one already on the message
correlation_id = message.correlation_id
```

The `correlation_id` is minted once, at ingress. It threads through understanding → context → workflow → business record → reply. Creating a new one severs the trace chain and makes debugging impossible.

---

### MUST NOT: Import from `mesiri.*` outside `backend/postgres/actor.py`

```python
# WRONG — in context/resolver.py or understanding/pipeline.py
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.domains.projects.models import Project

# CORRECT — import only from ports
from backend.ports import ActorReader, ActorIdentity
```

`apps/whatsapp-assistant/src/backend/ports.py` is the **capability boundary** between the assistant and the backend infrastructure. The only exception is `backend/postgres/actor.py`, which has explicit permission to cross this boundary.

---

### MUST NOT: Use `message.metadata["user_role"]` for authorization

```python
# WRONG — metadata is untrustworthy
if message.metadata.get("user_role") == "site_engineer":
    ...

# CORRECT — use the ActorIdentity from the identity gate
if actor.role == "site_engineer":
    ...
```

`metadata["user_role"]` is populated by an inline Postgres query inside `receiver._process_message()` — a known boundary violation scheduled for removal. The authoritative role is `ActorIdentity.role` resolved through `PostgresActorReader`.

---

## 3. Folder Structure and Module Responsibilities

```
apps/whatsapp-assistant/
├── src/
│   ├── backend/            ← backend capability boundary (ports + one postgres adapter)
│   ├── canonicalization/   ← normalizes UnderstandingResult + ResolvedContext into CanonicalEvent
│   ├── channel/            ← outbound WhatsApp message rendering
│   ├── context/            ← M4 context resolution (single ContextResolver — see §6)
│   ├── ingress/            ← M2 inbound pipeline
│   ├── interactions/       ← M7 human-in-the-loop (all files 0 bytes)
│   ├── memory/             ← M19 conversation memory (all files 0 bytes)
│   ├── planner/            ← M5 routing planner (implemented — routing.py, planner.py)
│   ├── projects/           ← HTTP API for project management
│   ├── runtime/            ← dependency injection, lifecycle, journey orchestration
│   ├── understanding/      ← M3 AI understanding pipeline
│   ├── users/              ← HTTP API for tenant user management
│   ├── workflows/          ← M6 LangGraph workflow runtime (all files 0 bytes)
│   ├── admin/              ← HTTP API for control plane
│   ├── auth/               ← HTTP API for mobile app authentication
│   └── main.py             ← ASGI entry point
├── tests/
│   ├── unit/               ← per-module tests (fake adapters only — no DB, no HTTP)
│   ├── contract/           ← cross-module contract tests
│   └── integration/        ← live stack tests (@pytest.mark.integration, skipped by default)
├── AGENTS.md               ← this file
├── README.md               ← human overview
├── Dockerfile
└── pyproject.toml
```

---

### `ingress/`

**Single responsibility:** Convert a raw Meta webhook payload into a `NormalizedMessage.v1`.

| File | What it does |
|---|---|
| `verification.py` | HMAC-SHA256 signature verification; webhook subscription challenge |
| `deduplication.py` | `InMemoryDeduplicationStore` — 24-hour TTL dedup by `message_id` |
| `media_ingestion.py` | `MetaMediaDownloader` — fetches binary media from Meta CDN |
| `media_handoff.py` | Uploads downloaded media to `ObjectStoragePort`, produces `MediaReference` |
| `normalization.py` | `MessageNormalizer` — maps Meta JSON to `NormalizedMessage.v1` |
| `receiver.py` | `WhatsAppReceiver` — orchestrates the above; schedules background tasks |

**Consumes:** Raw JSON from Meta webhook, binary media from Meta CDN  
**Produces:** `NormalizedMessage.v1`  
**Never does:** Business logic, database access, AI calls, context resolution

> ⚠️ **Known boundary violation:** `receiver._process_message()` contains an inline Postgres query that enriches `sender.profile_name` and `metadata["user_role"]`. This is SQL inside ingress — a violation. It must be removed. The identity gate in `_on_normalized()` handles user resolution correctly through `ActorReader`.

---

### `understanding/`

**Single responsibility:** Semantically interpret a `NormalizedMessage` into a structured `UnderstandingResult`.

| File | What it does |
|---|---|
| `pipeline.py` | `UnderstandingPipeline` — routes by modality, calls providers, scores confidence |
| `runtime.py` | `build_pipeline()` — provider selection; `format_reply()` — renders reply string |

**Modality routing:**
```
TEXT    → extraction.extract(text)
VOICE   → speech.transcribe(audio) → extraction.extract(transcript)
IMAGE   → vision.analyze_image(image) → extraction.extract(description)
```

**Provider selection** (in `runtime.py`):
```
SARVAM_API_KEY set    → SarvamSpeechProvider     else → FakeSpeechProvider
DEEPSEEK_API_KEY set  → DeepSeekExtractionProvider
GEMINI_API_KEY set    → GeminiProvider            else → FakeExtractionProvider
GEMINI_API_KEY set    → GeminiProvider (vision)   else → FakeVisionProvider
```

**Consumes:** `NormalizedMessage.v1`, bytes from `ObjectStoragePort`  
**Produces:** `UnderstandingResult.v1`  
**Never does:** Business logic, database access, context resolution, workflow selection, user-facing replies

Provider failures are caught as `MesiriError` and surfaced as `UNUSABLE` results. They are **never raised to the caller**.

---

### `context/`

**Single responsibility:** Resolve who is speaking, which org/project/site, what permissions they have, and how confident the resolver is.

> ✅ **RESOLVED (2026-07-08): the two-resolver issue is gone.** `ContractContextResolver` and its fake-only ports
> have been deleted entirely. The single canonical resolver is `ContextResolver` (`resolver.py`), producing
> `mesiri_contracts.assistant.resolved_context.ResolvedContext` — the only `ResolvedContext` schema left in the repo.

#### `ContextResolver` (`resolver.py`) — M4, production-grade, wired

- Uses 9 narrow ports backed by Postgres and Redis
- Output: `Result[ResolvedContext]` where schema is `mesiri_contracts.assistant.resolved_context.ResolvedContext`
- Ports: `ExternalIdentityRepository`, `OrganizationMembershipRepository`, `RolePermissionRepository`, `ProjectRepository`, `SiteRepository`, `ContextPreferenceRepository`, `ActiveContextStore`, `ReplyContextProvider`, `WorkflowContextProvider`
- **Status: Fully implemented, tested, and called in production** via `build_context_resolver()` in `context/runtime.py`, wired into `_on_normalized` by `runtime/dependencies.py`.
- `reply_context` / `workflow_context` ports are still `NullReplyContextProvider` / `NullWorkflowContextProvider` (`workflow_context.py`) — correctly so, since M5/M7 don't have active-workflow state to supply yet. Not a fake; an honest placeholder for a dependency that doesn't exist yet.

#### Other files

| File | What it does |
|---|---|
| `live_identity.py` | Orchestration bridge: `resolve_sender(reader, wa_id) → ActorIdentity`. Called before understanding, not after. |
| `context_policy.py` | Deterministic precedence: `MESSAGE_EXPLICIT > REPLY_CONTEXT > WORKFLOW_CONTEXT > ACTIVE_CONTEXT > USER_DEFAULT`. Pure — no LLM. |
| `active_context.py` | Redis-backed ephemeral last-known project/site. Never authoritative — always revalidated against Postgres. |
| `runtime.py` | `build_context_resolver()` wires the real Postgres/Redis adapters (falls back to `FakeRedis` only when `MESIRI_REDIS__HOST` is unset); `log_resolved_context()` dev diagnostics. |

---

### `runtime/`

**Single responsibility:** Wire all modules together. This is the only layer that knows about concrete implementations.

| File | What it does |
|---|---|
| `dependencies.py` | `Settings`, `AppContainer`, `build_container()`. The **only place** concrete adapters are selected. |
| `lifecycle.py` | `create_app()`, FastAPI lifespan, router mounting. |
| `inbound_journey.py` | `process_inbound_message()` — pure async orchestrator: understanding → context → reply. |
| `pipeline.py` | 0 bytes — reserved for future pipeline abstraction. |
| `dispatcher.py` | 0 bytes — reserved for future dispatch logic. |

> **Testability limitation:** `pipeline`, `sender`, and `actor_reader` are closure-captured inside `_on_normalized()` rather than being fields of `AppContainer`. They cannot be replaced in tests without rebuilding the entire container.

---

### `backend/`

**Single responsibility:** Define and enforce the capability boundary between the assistant and the backend infrastructure.

| File | What it does |
|---|---|
| `ports.py` | Defines `ActorReader` (Protocol), `ActorIdentity`, `ProjectSummary`, `SiteSummary`. This is everything the assistant is allowed to know about the backend. |
| `postgres/actor.py` | `PostgresActorReader`. The **only file** permitted to write SQL, hold a SQLAlchemy engine, or know table names. |

**Rule:** If the `users` table gains a new column, only `postgres/actor.py` changes. Nothing else in the assistant changes.

---

### `channel/`

**Single responsibility:** Render assistant outputs into WhatsApp message formats and send via Meta Cloud API.

**Consumes:** Strings, future structured reply specs  
**Produces:** HTTP calls to `graph.facebook.com`  
**Files:** `outbound.py`, `renderer.py`, `buttons.py`, `text.py`, `images.py`, `lists.py`, `documents.py`

---

### Implemented: `planner/`

`planner/` is no longer a stub. `Planner.decide(canonical_event)` (`planner.py`) is a pure, deterministic router —
receives a `CanonicalEvent`, emits a `PlannerDecision` via a static `routing.py` lookup table. It must never import
LangGraph or any specific graph. `ambiguity.py`, `decision.py`, and `prompts/` remain 0 bytes — no logic needed yet
(v1 intents are unambiguous, single-candidate).

### Stub modules — do not add logic yet

| Module | Purpose when built | Current state |
|---|---|---|
| `workflows/` | LangGraph graphs for material, expense, labour, equipment capture | All files 0 bytes |
| `interactions/` | Human-in-the-loop confirmations and field corrections | All files 0 bytes |
| `memory/` | Conversation history + semantic retrieval for Planner | All files 0 bytes |

**Do not implement business logic in any of these modules before the contracts are defined and cross-reviewed.**

---

### HTTP API modules (not part of the inbound pipeline)

`admin/`, `auth/`, `users/`, `projects/` are FastAPI routers for the control-plane dashboard and mobile app. They are mounted by `lifecycle.py` but are not involved in WhatsApp message processing.

---

## 4. Runtime Architecture

```
[WhatsApp Cloud API — Meta's servers]
              │
              │  POST /webhook (HMAC-SHA256 signed)
              ▼
┌─────────────────────────────────────────────┐
│  M2 — INGRESS  ✅ IMPLEMENTED               │
│  webhook.py → verification → deduplication  │
│  → media download → normalization           │
│  Produces: NormalizedMessage.v1             │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  IDENTITY GATE  ✅ IMPLEMENTED              │
│  PostgresActorReader → ActorIdentity        │
│  Gates: unregistered / no-org / suspended   │
│  Produces: ActorIdentity or early reply     │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  M3 — UNDERSTANDING  ✅ IMPLEMENTED         │
│  text → extraction                          │
│  voice → STT (Sarvam) → extraction          │
│  image → vision (Gemini) → extraction       │
│  Produces: UnderstandingResult.v1           │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  M4 — CONTEXT  ✅ WIRED (~90%)             │
│  ContextResolver — real Postgres/Redis      │
│  Produces: ResolvedContext                  │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  CANONICALIZATION  ✅ IMPLEMENTED          │
│  build_canonical_event()                    │
│  Produces: CanonicalEvent.v1                │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  M5 — PLANNER  ✅ IMPLEMENTED              │
│  Planner.decide() — pure routing            │
│  Produces: PlannerDecision.v1               │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  M6 — WORKFLOW RUNTIME  🔲 NOT IMPLEMENTED │
│  LangGraph not installed                    │
│  Will produce: WorkflowState + DraftAction  │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  M7 — INTERACTION  🔲 NOT IMPLEMENTED      │
│  Will produce: user confirmation request    │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  REPLY  ✅ IMPLEMENTED (M3-based only)     │
│  format_reply(UnderstandingResult)          │
│  WhatsAppSender.send_text()                 │
└─────────────────────────────────────────────┘
              │
              ▼
[WhatsApp Cloud API → worker's phone]
```

**Current production reality (2026-07-08):** Context, CanonicalEvent, and PlannerDecision are all produced on every
message and logged under `context_debug`, but the reply is still driven entirely by `UnderstandingResult` — none of
these three feed back into what gets sent to the user yet. Workflow Runtime and Interaction are not started; the
Workflow Runtime (M6, LangGraph) is the first real consumer of `PlannerDecision.workflow_key`.

---

## 5. Runtime Journey — Step by Step

This is exactly what happens today when a WhatsApp message arrives. No future state, no assumptions.

### Step 1 — Meta sends the webhook

```
POST /webhook
X-Hub-Signature-256: sha256=<hmac>
Content-Type: application/json

{"object": "whatsapp_business_account", "entry": [...]}
```

### Step 2 — Signature verification

`ingress/verification.py:verify_request_signature()` recomputes HMAC-SHA256 over raw body bytes using `WHATSAPP_APP_SECRET`. Mismatch → HTTP 403, message dropped silently.

### Step 3 — Payload routing

`ingress/webhook.py` checks `payload["object"] == "whatsapp_business_account"`. Anything else → HTTP 200, silently ignored. Meta sends other object types.

### Step 4 — Deduplication and background scheduling

`WhatsAppReceiver.handle_payload()` iterates entries. For each message:
1. `InMemoryDeduplicationStore.try_claim(message_id)` — already seen → skip. TTL = 24h. **In-memory only — state lost on restart.**
2. New → `asyncio.create_task(_process_message(context))` — HTTP 200 returned to Meta immediately.

**The webhook handler never blocks on processing.** Meta gets a fast response regardless of AI latency.

### Step 5 — Media download (image/voice only)

`MetaMediaDownloader.download(media_id)` fetches binary from Meta CDN. Returns `DownloadedMedia` with local path, MIME type, SHA256, and size in bytes.

### Step 6 — Object storage upload

`upload_downloaded_media()` calls `build_object_storage(settings).put_object(key, data)`, returns a `MediaReference(object_key, mime_type, size_bytes)`.

> ⚠️ `R2ObjectStorage` exists (`mesiri.infrastructure.objectstorage.r2`) but `FakeObjectStorage` is still the default —
> in-memory, media lost on process restart — unless `MESIRI_OBJECT_STORAGE__PROVIDER=r2` is set with credentials in
> the deployment environment. Remaining work is deployment config + a live verification, not code.

### Step 7 — Normalization

`MessageNormalizer.normalize()` maps Meta JSON → `NormalizedMessage.v1`:

| Field | Source |
|---|---|
| `message_id` | `message["id"]` |
| `correlation_id` | Auto-generated `cor_<uuid>` — never regenerate downstream |
| `channel` | `"whatsapp"` |
| `sender.wa_id` | `message["from"]` |
| `modality` | `text`→`TEXT`, `audio.voice`→`VOICE`, `image`→`IMAGE` |
| `text` | Body (text) or caption (image) |
| `media` | `MediaReference` if applicable |
| `reply_context` | `ReplyContext(replied_to_message_id)` if a reply |

> ⚠️ `receiver._process_message()` runs an inline Postgres query here to enrich `sender.profile_name`. This is a boundary violation. Do not extend or rely on it.

**Contract produced: `NormalizedMessage.v1`**

### Step 8 — Identity gate

`resolve_sender(actor_reader, wa_id)` → `PostgresActorReader.resolve_by_whatsapp_id(wa_id)`.

| Result | Action |
|---|---|
| `None` (unregistered) | Send `UNREGISTERED_MESSAGE`, return |
| `organization_id is None` | Send `NO_ORG_MESSAGE`, return |
| `not org_active` | Send `ORG_SUSPENDED_MESSAGE`, return |
| Pass | Continue with `ActorIdentity` in scope |

**Contract at this point: verified, active, org-affiliated user.**

### Step 9 — Understanding pipeline (M3)

`UnderstandingPipeline.understand(message)`:

```
TEXT:  extraction.extract(text)              → ExtractionResult
VOICE: speech.transcribe(audio_bytes)        → SpeechResult
       extraction.extract(transcript)         → ExtractionResult
IMAGE: vision.analyze_image(image_bytes)     → VisionResult
       extraction.extract(description)        → ExtractionResult
```

`ConfidencePolicy.evaluate(signals)` → `HIGH / MEDIUM / LOW / UNUSABLE`

Provider `MesiriError` → result is `UNUSABLE`, never raised.

**Contract produced: `UnderstandingResult.v1`**

### Step 10 — Context resolution (M4, real Postgres/Redis)

`ContextResolver.resolve(message, understanding)` queries real Postgres repositories for identity, membership,
role/permissions, project, and site, plus a Redis-backed active-context store (falls back to `FakeRedis` only when
`MESIRI_REDIS__HOST` is unset). Returns `Result[ResolvedContext]` — errors are logged and short-circuit the rest of
the journey (canonicalization/planning are skipped) rather than propagating a bad state.

If `WHATSAPP_CONTEXT_DEBUG=true`: `log_resolved_context()` writes actor/org/project/site/confidence to logger.

### Step 11 — Canonicalization

`build_canonical_event(understanding, resolved)` (in `canonicalization/`) maps the `UnderstandingResult` +
`ResolvedContext` into a `CanonicalEvent.v1` — a normalized business-intent signal (e.g. `MaterialReceiptRequested`).
Per architecture, it never carries the AI's raw confidence score; `completeness` (actionable / needs_clarification /
not_actionable) is a business-level judgement over which required fields are present instead.

If `WHATSAPP_CONTEXT_DEBUG=true`: `log_canonical_event()` writes it to logger.

### Step 12 — Planning

`Planner().decide(canonical_event)` (in `planner/`) is a pure, deterministic router — no LLM, no I/O, no knowledge of
LangGraph or any specific graph. It returns a `PlannerDecision.v1`: `START_WORKFLOW` + a `workflow_key` (e.g.
`material.receipt`) for actionable domain intents, `CLARIFY` for incomplete ones, `DIRECT_REPLY` for questions/
unrecognized input. A `model_validator` on the contract enforces `workflow_key` is set if and only if the decision is
`START_WORKFLOW`.

If `WHATSAPP_CONTEXT_DEBUG=true`: `log_planner_decision()` writes it to logger.

**Context, CanonicalEvent, and PlannerDecision are all produced but currently unused by the reply.** They are
skipped entirely if context resolution fails.

### Step 13 — Reply

`format_reply(understanding)` builds the reply from `UnderstandingResult` only. `WhatsAppSender.send_text(wa_id, text)` sends via Meta Cloud API.

**The reply has no dependency on context, the canonical event, or the planner decision yet.** The Workflow Runtime
(M6) will be the first real consumer of `PlannerDecision`.

---

## 6. Current Implementation Status

| Module | Status | % | Critical gaps |
|---|---|---|---|
| Ingress (M2) | ✅ Implemented | 100% | Inline SQL removed (2026-07-08); `FakeObjectStorage` used unless `MESIRI_OBJECT_STORAGE__PROVIDER=r2` is configured |
| Understanding (M3) | ✅ Implemented | 100% | None before Workflow Runtime |
| Context (M4) | ✅ Wired | 90% | `ContractContextResolver` retired (2026-07-08); real Postgres/Redis in production. Remaining: `reply_context`/`workflow_context` are `Null` providers pending M5/M7; no `FakeActorReader` yet |
| Identity Gate | ✅ Implemented | 100% | No `FakeActorReader` — identity gate tests require live DB |
| Canonicalization | ✅ Implemented | 100% | `CanonicalEvent.v1` wired into the journey (2026-07-08); not yet consumed downstream |
| Planner (M5) | ✅ Implemented | 100% | `PlannerDecision.v1` wired (2026-07-08); pure router, no LangGraph knowledge. Not yet consumed by anything (Workflow Runtime is the first real consumer) |
| Workflow Runtime (M6) | 🔲 Not started | 0% | LangGraph not installed; `WorkflowState`/`DraftAction` contracts not defined |
| Interaction (M7) | 🔲 Not started | 0% | Contracts not defined |
| Application & Domain Execution (M8) | 🔲 Not started | 0% | Application and domain missing for material |
| Memory (M19) | 🔲 Not started | 0% | `platform/memory/` entirely empty |
| Rules | 🔲 Not started | 0% | `rules/result.py` is 0 bytes |
| Tools | 🔲 Not started | 0% | All tool contracts 0 bytes |
| Authorization (RBAC) | ⚠️ Gate only | 30% | Identity gate works; field-level RBAC not enforced — Context resolves `permissions` now, but nothing downstream consumes them yet |
| Rendering | ✅ M3-based | 60% | Plain-text only; no templates, no confirmation cards |

### Next required steps (in order)

1. Add `FakeActorReader` for identity gate testing
2. Configure `MESIRI_OBJECT_STORAGE__PROVIDER=r2` + credentials in deployment; verify live (adapter already exists)
3. Define minimum Memory (conversation history) — a prerequisite for Workflow Runtime checkpointing
4. Define `WorkflowState` + `DraftAction` contracts (requires Alan + Ilan review)
5. Install LangGraph and implement the Material workflow (the doc's designated proof-of-architecture module)
6. Wire `Workflow Registry` (`workflow_key → graph`) as the seam between Planner and LangGraph

---

## 7. Contracts

All shared contracts live in `shared/contracts/src/mesiri_contracts/`. **Never define contracts inside this folder.**

### `NormalizedMessage.v1`

| | |
|---|---|
| **File** | `mesiri_contracts/assistant/normalized_message.py` |
| **Producer** | `ingress/normalization.py` |
| **Consumers** | Understanding pipeline, Context resolver, Identity gate |
| **Why** | Decouples Meta's proprietary webhook format from all downstream logic |
| **Key fields** | `message_id`, `correlation_id`, `channel`, `sender.wa_id`, `modality`, `text`, `media`, `reply_context` |
| **Status** | **Frozen. Do not modify without cross-review.** |

### `UnderstandingResult.v1`

| | |
|---|---|
| **File** | `mesiri_contracts/assistant/understanding_result.py` |
| **Producer** | `understanding/pipeline.py` |
| **Consumers** | Context resolver, reply formatter, future Planner |
| **Why** | Decouples AI provider output from downstream business logic. Provider can change; shape stays constant. |
| **Key fields** | `semantic_type`, `candidates`, `overall_confidence`, `transcript`, `translated_text`, `document_classification`, `missing_fields` |
| **Status** | **Frozen. Do not modify without cross-review.** |

### `ResolvedContext.v1` (the only `ResolvedContext` schema — the contract-layer duplicate was deleted 2026-07-08)

| | |
|---|---|
| **File** | `mesiri_contracts/assistant/resolved_context.py` |
| **Producer** | `context/resolver.py` (`ContextResolver`) |
| **Consumers** | `canonicalization/builder.py` |
| **Why** | Single authoritative answer: who is this, where are they, what can they do? |
| **Key fields** | `organization_id`, `user_id`, `role_ids`, `permissions`, `project_id`, `site_id`, `context_source`, `context_confidence` |
| **Status** | Implemented and wired into production. |

### `CanonicalEvent.v1`

| | |
|---|---|
| **File** | `mesiri_contracts/assistant/canonical_event.py` |
| **Producer** | `canonicalization/builder.py` (`build_canonical_event`) |
| **Consumers** | `planner/planner.py` |
| **Why** | Normalizes AI output into business intent. Per the architecture's layer-ownership rule it must never carry AI-provider or confidence-score knowledge — `completeness` is a business-level judgement over required fields instead. |
| **Key fields** | `event_type` (`CanonicalEventType`, e.g. `MaterialReceiptRequested`), `completeness`, `organization_id`, `user_id`, `project_id`, `site_id`, `fields`, `missing_fields` |
| **Status** | Implemented and wired into production (2026-07-08). |

### `PlannerDecision.v1`

| | |
|---|---|
| **File** | `mesiri_contracts/assistant/planner_decision.py` |
| **Producer** | `planner/planner.py` (`Planner.decide`) |
| **Consumers** | Future Workflow Registry (M6) |
| **Why** | The Planner "reads CanonicalEvent, returns a workflow_key" — must never know about LangGraph or any specific graph. |
| **Key fields** | `decision_type` (`start_workflow`/`clarify`/`direct_reply`/`ignore`), `workflow_key` (`WorkflowKey`, set only for `start_workflow` — enforced by a `model_validator`), `reason` (typed `CanonicalEventType`, diagnostic-only), `organization_id`, `user_id`, `project_id`, `site_id`, `missing_fields` |
| **Status** | Implemented and wired into production (2026-07-08). Not yet consumed — Workflow Runtime (M6) will be the first real consumer. |

### `ActorIdentity`

| | |
|---|---|
| **File** | `backend/ports.py` (local to this folder — not shared) |
| **Producer** | `backend/postgres/actor.py` |
| **Consumers** | `context/live_identity.py`, `runtime/dependencies.py` |
| **Why** | The backend capability boundary surface — exactly what the assistant needs to know about an actor |
| **Status** | Stable. |

### Contracts not yet defined (0 bytes)

| Contract | File | Required by |
|---|---|---|
| `WorkflowState` | TBD | Workflow Runtime (M6) |
| `DraftAction` | TBD | Workflow Runtime → Application Layer |
| `InteractionSpec` | TBD | Interaction (M7) |

---

## 8. Ports and Adapters

### Philosophy

Every external dependency is hidden behind a Python `Protocol`. Core logic depends on the protocol only. Concrete adapters are injected at startup by `build_container()`. Tests inject fake adapters. This means the entire assistant can be tested without any live infrastructure.

### Complete port table

| Port | Defined in | Fake adapter | Production adapter |
|---|---|---|---|
| `SpeechUnderstandingProvider` | `platform/ai/ports/speech.py` | `FakeSpeechProvider` | `SarvamSpeechProvider` |
| `VisionUnderstandingProvider` | `platform/ai/ports/vision.py` | `FakeVisionProvider` | `GeminiProvider` |
| `StructuredExtractionProvider` | `platform/ai/ports/extraction.py` | `FakeExtractionProvider` | `GeminiProvider`, `DeepSeekExtractionProvider` |
| `ObjectStoragePort` | `mesiri_contracts/common/storage.py` | `FakeObjectStorage` | ⚠️ No real adapter wired |
| `ActorReader` | `backend/ports.py` | ⚠️ No fake | `PostgresActorReader` |
| `DeduplicationStore` | `ingress/deduplication.py` | `InMemoryDeduplicationStore` | ⚠️ No Redis adapter |
| `IdentityLookupPort` | `mesiri_contracts/context/ports.py` | `FakeIdentityLookupPort` | ⚠️ None |
| `ScopeLookupPort` | `mesiri_contracts/context/ports.py` | `FakeScopeLookupPort` | ⚠️ None |
| `WorkflowStateReadPort` | `mesiri_contracts/context/ports.py` | `FakeWorkflowStateReadPort` | ⚠️ None |
| `ExternalIdentityRepository` (M4) | `context/ports.py` | `FakeExternalIdentityRepository` | `PostgresExternalIdentityRepository` |
| `ProjectRepository` (M4) | `context/ports.py` | `FakeProjectRepository` | `PostgresProjectRepository` |
| `SiteRepository` (M4) | `context/ports.py` | `FakeSiteRepository` | `PostgresSiteRepository` |
| `ActiveContextStore` (M4) | `context/ports.py` | `FakeActiveContextStore` | `RedisActiveContextStore` |

**⚠️ Missing real adapters:**
- `ObjectStoragePort` — media lost on restart
- Redis `DeduplicationStore` — duplicates allowed across restarts
- `IdentityLookupPort` / `ScopeLookupPort` — required to retire fake context adapters
- `FakeActorReader` — identity gate cannot be tested without a live database

---

## 9. Dependency Rules

### Allowed imports by module

| Module | May import from |
|---|---|
| `ingress/` | `mesiri_contracts.assistant.*`, `mesiri_contracts.common.*` |
| `understanding/` | `mesiri_ai.ports.*`, `mesiri_contracts.assistant.*`, `mesiri_contracts.common.*` |
| `context/` | `mesiri_contracts.assistant.*`, `mesiri_contracts.context.*`, `mesiri_contracts.common.*`, `backend.ports` |
| `backend/postgres/actor.py` | `mesiri.*` — this is the only file with this permission |
| `runtime/` | All modules in `src/` — this is the wiring layer |
| `channel/` | `mesiri_contracts.*` |
| Any module | `mesiri_contracts.*`, `mesiri_ai.ports.*` |

### Prohibited imports

| Module | Must NOT import |
|---|---|
| `ingress/` | `context/`, `understanding/`, `backend/postgres/`, `mesiri.*` |
| `understanding/` | `context/`, `ingress/`, `mesiri.*` (except via ports) |
| `context/` (except `main_table_repositories.py`) | `mesiri.infrastructure.*`, ORM models, table names |
| Any module | AI SDKs directly (`google.generativeai`, `anthropic`, `openai`, `sarvam`) |
| Any module (except `backend/postgres/`) | `sqlalchemy`, `asyncpg`, raw SQL strings |
| Any module | Contracts defined inside `apps/whatsapp-assistant/src/` |

### Dependency direction

```
runtime/ (wiring — may import everything)
    │
    ▼
ingress/ → understanding/ → context/ → planner/ → workflows/ → interactions/
    │              │             │
    ▼              ▼             ▼
backend/        mesiri_ai/    mesiri_contracts/
(ports only)    (ports only)  (shared, canonical)
```

**Dependencies flow downward and inward only.** Ingress must not know about context. Context must not know about workflows. Each layer is ignorant of layers above it.

---

## 10. Design Principles

### Contracts First

Every module boundary is a Pydantic model in `shared/contracts/`. If two modules share data, a contract must exist first. No module depends on another module's internal structures.

**Why:** Without contracts, a change to `UnderstandingResult` cascades through ingress, context, and planner at the same time. With contracts, cascades are explicit, reviewable, and bounded.

### Ports and Adapters

All I/O (database, cache, AI, object storage, external HTTP) is hidden behind a `Protocol`. Business logic depends only on protocols. The assistant can be tested entirely without live infrastructure.

**Why:** Providers change constantly. Isolating SDK contact in `platform/ai/` means a model migration requires changing exactly one adapter file.

### Dependency Injection at the Boundary

`build_container()` in `runtime/dependencies.py` is the only place where concrete implementations are selected. No module creates its own dependencies.

**Why:** If a module creates its own database connection, it cannot be tested in isolation. DI makes substitution trivial and the dependency graph explicit.

### AI Provider Isolation

The assistant never imports a provider SDK. It imports from `mesiri_ai.ports.*`. The gateway in `platform/ai/` owns SDK imports, retry logic, model selection, and fallback.

**Why:** Models are deprecated, APIs shift, pricing changes. All SDK contact in `platform/ai/` means provider migrations touch exactly one adapter.

### Single Responsibility

Each module does exactly one thing. `ingress/` normalizes. `understanding/` interprets. `context/` scopes. `planner/` routes. When something breaks, the boundaries tell you exactly where to look.

### Stateless Processing

Each message is processed independently. No in-memory state is shared between invocations. Future conversation state will be stored in Redis/PostgreSQL and loaded per-request.

**Why:** Stateless processing enables horizontal scaling and eliminates a class of race conditions.

### Business Logic Separation

The assistant routes and orchestrates. It does not contain domain rules. "A material receipt requires quantity > 0" belongs in the domain service — not in a LangGraph node.

**Why:** Domain rules change with the business. Rules in workflow nodes require code deployments to change.

### Human-in-the-Loop

The Interaction layer (M7) exists for cases where the AI is not confident enough to commit data automatically. The user's confirmation response re-enters via ingress and is matched to the pending interaction.

**Why:** In construction, wrong quantities are expensive. The confirmation loop is a first-class architectural concern.

### Correlation ID Propagation

`correlation_id` is minted once, at ingress. Every downstream step, every log statement, every port call must carry the same ID. Never regenerate it.

**Why:** Without it, debugging a failed message requires reconstructing its journey from timestamps. With it, one `grep` produces the complete trace.

---

## 11. Common Mistakes

These are the patterns AI agents introduce most often. Every one violates the architecture.

---

### Mistake 1: Writing SQL outside `backend/postgres/actor.py`

```python
# WRONG
from sqlalchemy import text
result = await conn.execute(
    text("SELECT id FROM users WHERE whatsapp_number = :n"), {"n": wa_id}
)

# CORRECT
actor = await self._actor_reader.resolve_by_whatsapp_id(wa_id)
```

---

### Mistake 2: Importing ORM models or SQLAlchemy outside `backend/postgres/`

```python
# WRONG — in understanding/pipeline.py
from mesiri.infrastructure.postgres.models.user import User

# CORRECT — never needed in understanding/
# If you feel you need it, the design is wrong. Re-read §1.
```

---

### Mistake 3: Defining a contract inside this folder

```python
# WRONG — apps/whatsapp-assistant/src/my_module/events.py
class ReceiptCreatedEvent(BaseModel):
    receipt_id: str

# CORRECT — shared/contracts/src/mesiri_contracts/events/receipt.py
class ReceiptCreatedEvent(BaseModel):
    receipt_id: str
```

---

### Mistake 4: Calling an AI SDK directly

```python
# WRONG
import google.generativeai as genai
model = genai.GenerativeModel("gemini-2.5-flash")

# CORRECT
result = await self._extraction.extract(text, correlation_id=correlation_id)
```

---

### Mistake 5: Importing context from inside the understanding pipeline

```python
# WRONG — understanding/pipeline.py
from context.resolver import ContextResolver
actor = await ContextResolver(...).resolve(...)

# CORRECT — these are separate stages, orchestrated in inbound_journey.py
understanding = await pipeline.understand(message)
resolved = await context_resolver.resolve(message, understanding)
```

---

### Mistake 6: Putting business validation in a LangGraph node

```python
# WRONG
def validate_quantity(state):
    if state["quantity"] <= 0:
        raise ValueError("Invalid quantity")

# CORRECT — let the domain service validate
await material_service.record_receipt(CreateReceiptCommand(...))
```

---

### Mistake 7: Using `message.metadata["user_role"]` for authorization

```python
# WRONG
if message.metadata.get("user_role") == "site_engineer":
    ...

# CORRECT
if actor.role == "site_engineer":
    ...
```

---

### Mistake 8: Generating a new `correlation_id` mid-journey

```python
# WRONG
import uuid
correlation_id = str(uuid.uuid4())  # severs the trace chain

# CORRECT
correlation_id = message.correlation_id
```

---

### Mistake 9: Adding shared mutable state to `_on_normalized` via closure

```python
# WRONG — concurrent messages will race on this
message_count = 0
async def _on_normalized(message):
    nonlocal message_count
    message_count += 1  # race condition

# CORRECT — all message-scoped state is local to each invocation
```

---

## 12. Development Checklist

Before creating or modifying any module, verify every item.

### Architecture
- [ ] Does this module have exactly one responsibility?
- [ ] Is that responsibility listed in §1?
- [ ] Does it introduce a dependency that goes against the direction in §9?
- [ ] Does this touch M2 or M3? If yes, both Alan and Ilan must review.

### Contracts
- [ ] If this module produces data for another module, is there a shared contract in `shared/contracts/`?
- [ ] Are you importing contracts from `mesiri_contracts.*`? Not defining them inside `src/`?
- [ ] Did you verify the contract doesn't already exist in `shared/contracts/src/mesiri_contracts/`?

### Ports and Adapters
- [ ] Does this module do I/O? (database, AI, cache, HTTP) → Is it behind a port?
- [ ] Is there a fake adapter so unit tests run without infrastructure?
- [ ] Does the fake adapter honour the same contract as the real one?

### Tests
- [ ] Unit tests use only fake adapters — no live DB, no API keys, no HTTP
- [ ] Contract tests verify output validates against the shared contract schema
- [ ] Integration tests are `@pytest.mark.integration` and skipped by default in CI

### Boundaries
- [ ] No SQL outside `backend/postgres/actor.py`
- [ ] No AI SDK imports outside `platform/ai/adapters/`
- [ ] No `mesiri.infrastructure.*` imports outside `backend/postgres/actor.py`
- [ ] No contracts defined inside `apps/whatsapp-assistant/src/`
- [ ] No business rules in workflow nodes, pipeline steps, or context policy

### Dependency Injection
- [ ] Does the module accept all external dependencies as constructor arguments?
- [ ] Are dependencies registered in `build_container()` in `runtime/dependencies.py`?
- [ ] Can the module be instantiated in a test with fake dependencies and no env vars?

### Correlation
- [ ] Does every log statement include `correlation_id`?
- [ ] Is `correlation_id` propagated from the input message — never regenerated?

---

## 13. Glossary

**Contract** — A Pydantic `BaseModel` in `shared/contracts/` describing data exchanged between modules. Versioned (`v1`, `v2`). Changes require cross-team review. Example: `NormalizedMessage.v1`.

**Port** — A Python `Protocol` defining the interface of an external dependency. Business logic depends on ports, never on concrete implementations. Example: `StructuredExtractionProvider`.

**Adapter** — A concrete class implementing a port. Two kinds: **fake** (in-memory, deterministic, for tests) and **production** (real SDK / network). Example: `GeminiProvider` implements `StructuredExtractionProvider`.

**Resolver** — A class that takes structured input and produces richer output by querying ports. Always read-only. Example: `ContextResolver` → `ResolvedContext`.

**Identity Gate** — The check immediately after ingress: is the sender registered, org-affiliated, and active? If not, reply and stop. No AI compute is spent on unknown users.

**Correlation ID** — A `cor_<uuid>` string minted at ingress. Every log line, port call, and downstream service call must carry it unchanged. Enables end-to-end tracing.

**Workflow** — A stateful, multi-turn LangGraph graph that collects business data from a user across one or more messages. Example: material usage workflow.

**Application Layer** — The translation layer from `DraftAction` to domain service calls. Owns command construction, not business rules.

**Domain** — Business entities and rules owned by the backend. Material receipts, expenses, labour reports. The assistant never accesses the domain directly.

**Canonical Event** — A domain event produced when a workflow commits data. Flows to the event bus and timeline. Example: `MaterialReceiptCreated`.

**Planner** — Decides, given `ResolvedContext` + `UnderstandingResult`, which workflow to start/continue/clarify or whether to reply directly. Produces `PlannerDecision`.

**Interaction** — A human-in-the-loop confirmation, field clarification, or correction before a workflow commits data. Re-enters via ingress and is matched to a pending interaction record.

**Checkpoint** — A LangGraph state snapshot persisted to Redis after each workflow step. Enables workflow resumption after process restart.

**Context** — The resolved business scope: actor, org, project, site, permissions, and confidence. Produced by `ContextResolver`, consumed by Planner.

**Workflow Runtime** — The LangGraph execution environment. Manages graph state, transitions, and checkpoint persistence. Contains no business logic.

**Tool Executor** — A controlled interface through which workflows call external services. Validates inputs, calls the tool, returns the result. No workflow calls external services except through this.

**Memory** — Conversation history and semantic retrieval for the Planner. Minimum: last N turns. Full: pgvector semantic search across all prior messages.

**Rules Engine** — Externalized configurable business rules (approval thresholds, quantity limits). Evaluated by the Application Layer before committing data.

---

*Reflects codebase state: 2026-07-08. Update this file whenever the architecture changes.*
