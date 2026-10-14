# WhatsApp Assistant

The primary human-facing interface of Mesiri. Construction site workers send WhatsApp messages — text, voice notes, or photos — and this service converts them into structured business records without forms, apps, or data entry.

> For architectural rules, dependency constraints, port tables, common mistakes, and the development checklist, see [AGENTS.md](./AGENTS.md).

---

## What it does

A site engineer sends a voice note: *"received 20 bags cement today"*

The assistant:
1. Verifies the message is from Meta (HMAC-SHA256)
2. Confirms the sender is a registered, active Mesiri user
3. Transcribes and translates the voice note (Sarvam STT)
4. Extracts structured fields: `material_name: cement`, `quantity: 20`, `unit: bags`
5. Scores confidence in the extraction
6. Replies with a structured summary on WhatsApp

Eventually (Planner + Workflow not yet built):
- Routes to the correct workflow (material receipt, expense, labour, etc.)
- Asks for missing fields if needed
- Asks the user to confirm before saving
- Commits the record to the backend

---

## Where it sits in Mesiri

```
[WhatsApp Cloud API]   ← Meta's servers
         │
         ▼
[WhatsApp Assistant]   ← this service — AI conversation layer
         │
         ▼
[Backend Domain API]   ← business records, user management
         │
         ▼
[PostgreSQL + Redis]   ← persistence
         │
         ▼
[Mobile App]           ← managers review structured data
```

The assistant is the **front door for field workers**. The backend is the **source of truth for business data**. They share the same PostgreSQL database but are separate services.

---

## High-Level Architecture

```
[Meta webhook POST]
        │
        ▼
  Ingress            ✅  verify → dedup → normalize → media
        │
        ▼
  Identity Gate      ✅  block unregistered / no-org / suspended
        │
        ▼
  Understanding      ✅  text / voice / image → structured fields
        │
        ▼
  Context            ⚠️  who/project/site — partially wired
        │
        ▼
  Planner            🔲  route to correct workflow
        │
        ▼
  Workflow Runtime   🔲  LangGraph — collect missing fields
        │
        ▼
  Interaction        🔲  ask user to confirm before saving
        │
        ▼
  [Backend]          ←   commit the record
        │
        ▼
  Reply              ✅  send WhatsApp message back
```

**Today:** The pipeline runs Ingress → Identity Gate → Understanding → (partial) Context → Reply. Planner and Workflow are not yet built.

---

## Current Milestone Status

| Module | Status | Notes |
|---|---|---|
| Ingress (M2) | ✅ 100% | Signature verify, dedup, normalization, media download |
| Understanding (M3) | ✅ 100% | Text, voice (Sarvam), image (Gemini), confidence scoring |
| Identity Gate | ✅ 100% | Postgres-backed; blocks unregistered/suspended users |
| Context (M4) | ⚠️ 65% | M4 resolver built but not wired; fake adapters in production |
| Planner (M5) | 🔲 0% | Folder declared; all files empty; contract not defined |
| Workflow Runtime (M6) | 🔲 0% | LangGraph not installed; contracts not defined |
| Interaction (M7) | 🔲 0% | Folder declared; all files empty |
| Application & Domain Execution (M8) | 🔲 0% | Not started |
| Memory (M19) | 🔲 0% | Not started |
| Reply | ✅ | M3-based plain text only; no templates yet |

### Known gaps to fix before Planner

1. Remove inline SQL from `ingress/receiver._process_message()` (boundary violation)
2. Wire real object storage adapter (media lost on process restart today)
3. Unify the two `ResolvedContext` schemas into one canonical contract
4. Wire M4 `ContextResolver` (fully built, just not called in production)
5. Define `PlannerDecision` contract (requires Alan + Ilan review)

---

## Folder Overview

```
src/
├── ingress/          M2 — webhook, dedup, normalization, media
├── understanding/    M3 — AI pipeline (speech, vision, extraction, confidence)
├── context/          M4 — context resolution (two implementations — see AGENTS.md)
├── planner/          M5 — stub (empty)
├── workflows/        M6 — stub (empty)
├── interactions/     M7 — stub (empty)
├── memory/           M19 — stub (empty)
├── backend/          Capability boundary — ports + one Postgres adapter
├── channel/          Outbound WhatsApp rendering
├── runtime/          DI container, lifecycle, inbound journey orchestration
├── auth/             HTTP API — mobile app JWT login
├── admin/            HTTP API — organization admin endpoints
├── users/            HTTP API — tenant user CRUD
├── projects/         HTTP API — project and site management
└── main.py           ASGI entry point
```

---

## Running Locally

### Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or pip
- PostgreSQL (for the identity gate — see `.env`)
- A Meta WhatsApp Business API app (for live webhook testing)

### Install

```bash
cd apps/whatsapp-assistant
uv pip install -e ".[dev]"
```

Or with pip:

```bash
pip install -e ".[dev]"
```

### Run

```bash
uvicorn main:app --reload --port 8000
```

The service starts at `http://localhost:8000`. The webhook endpoint is `POST /webhook`.

### Test

```bash
# Unit tests (no DB, no API keys required)
pytest tests/unit/

# Contract tests
pytest tests/contract/

# Integration tests (requires live DB + API keys)
pytest tests/integration/ -m integration
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values. All variables use the `WHATSAPP_` prefix (via `pydantic-settings`).

| Variable | Required | Description |
|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | ✅ | Meta webhook subscription challenge token |
| `WHATSAPP_APP_SECRET` | ✅ | Meta app secret for HMAC-SHA256 signature verification |
| `WHATSAPP_ACCESS_TOKEN` | ✅ | Meta permanent or system user access token |
| `WHATSAPP_PHONE_NUMBER_ID` | ✅ | Meta phone number ID for outbound messages |
| `WHATSAPP_API_VERSION` | — | Meta API version (default: `v21.0`) |
| `WHATSAPP_GRAPH_BASE_URL` | — | Override for Meta Graph API base (default: `https://graph.facebook.com`) |
| `WHATSAPP_MEDIA_DOWNLOAD_DIR` | — | Local path for temporary media files (default: `/tmp/mesiri/whatsapp-media`) |
| `WHATSAPP_DEDUP_TTL_HOURS` | — | Deduplication window in hours (default: `24`) |
| `WHATSAPP_CONTEXT_DEBUG` | — | Set to `true` to log `ResolvedContext` after each message (dev only) |
| `WHATSAPP_APPROVED_TEMPLATES` | — | Comma-separated Meta-approved template names Mesiri may send outside the 24 h window (default: none). See [docs/ops/whatsapp-templates.md](../../docs/ops/whatsapp-templates.md) |

AI provider keys (set in platform-level settings, not `WHATSAPP_` prefix):

| Variable | Description | Fallback |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini (vision + extraction) | `FakeVisionProvider` + `FakeExtractionProvider` |
| `DEEPSEEK_API_KEY` | DeepSeek (extraction, preferred over Gemini if set) | Falls back to Gemini |
| `SARVAM_API_KEY` | Sarvam (speech-to-text + translation) | `FakeSpeechProvider` (fixture audio) |

Database (for identity gate):

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |

> If no AI provider keys are set, the service runs with fake providers that return deterministic fixture data. This is useful for local development and testing without API credits.

---

## Key Architectural Decisions

These decisions are non-negotiable and explain why the codebase looks the way it does.

**Contracts first** — every module boundary is a Pydantic model in `shared/contracts/`. No module depends on another module's internals.

**Ports and adapters** — all I/O (DB, AI, cache, storage) is behind a Python `Protocol`. Fake adapters allow full testing without infrastructure. Real adapters are injected at startup.

**SQL belongs in exactly one file** — `backend/postgres/actor.py`. Nothing else in this service queries the database directly.

**AI providers are isolated in `platform/ai/`** — the assistant imports ports, never SDKs. Provider swaps require changing one adapter file.

**Context has two implementations today** — this is a known debt. The M4 `ContextResolver` (Postgres/Redis-backed) is fully built but not yet wired. `ContractContextResolver` runs in production with fake adapters. This will be unified before Planner is implemented.

**The reply is M3-based today** — the current reply is generated directly from `UnderstandingResult`. Context resolution runs but does not affect the reply yet.

---

## Future Roadmap

### Near term (before Planner)
- Unify `ResolvedContext` schema and wire M4 `ContextResolver` into production
- Wire real object storage (R2/S3) — media is lost on restart today
- Add `FakeActorReader` for identity gate testing
- Define `PlannerDecision` contract

### Medium term (Planner + first workflow)
- Implement Planner — routes messages to the correct workflow
- Implement first LangGraph workflow — material usage / expense capture
- Implement Interaction layer — human-in-the-loop confirmations

### Long term
- Conversation memory (M19 - pgvector semantic retrieval)
- Rules engine (configurable approval thresholds, quantity limits)
- Tool executor (external service calls from workflows)
- Rich WhatsApp reply templates (buttons, lists, confirmation cards)
- Timeline (canonical events → project history feed)

---

## Related Folders

| Path | What it is |
|---|---|
| `shared/contracts/` | All shared Pydantic contracts (`NormalizedMessage`, `UnderstandingResult`, etc.) |
| `platform/ai/` | AI provider adapters, ports, gateway, confidence policy |
| `platform/memory/` | Conversation memory (empty — future) |
| `backend/` | Backend domain API, PostgreSQL schema, Alembic migrations |
| `apps/mobile/` | React Native mobile app for managers |

---

*Last updated: July 2026*
