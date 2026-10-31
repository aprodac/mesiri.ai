# WhatsApp Assistant

The primary human-facing interface of Mesiri. Construction site workers send WhatsApp messages — text, voice notes, or photos — and this service converts them into structured business records without forms, apps, or data entry.

> For architectural rules, dependency constraints, port tables, common mistakes, and the development checklist, see [AGENTS.md](./AGENTS.md).

---

## What it does

A site engineer sends a voice note: *"received 20 bags cement today"*

The assistant (v2): one agent reads the message, decides what it holds, calls tools (put a receipt line on the
draft card, look up stock, ...) and writes its own reply in the sender's language. The worker taps **Save**
and only then is anything written. Before that, the message is verified (Meta HMAC-SHA256), the sender is
checked as a registered, active Mesiri user, and a voice note is transcribed.

> Status: v2 is live **only on the 2 test companies**; real customers still run the classic path. v2's live
> gate (>= 90% right, 0 wrong saves) is not passed yet. Full architecture:
> [docs/architecture/assistant-v2.md](../../docs/architecture/assistant-v2.md).

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
  Ingress            ✅  verify → dedup → normalize → media (voice → text)
        │
        ▼
  Identity Gate      ✅  block unregistered / no-org / suspended
        │
        ▼
  Journey            ✅  taps, site questions, pending Yes/No, held photos keep their handlers
        │
        ▼
  assistant_mode     ✅  per-company setting
     ├─ v2 / v2_shadow ⚠️  agent_v2: ONE agent + skills + tools        (2 test companies only)
     └─ classic        ✅  today's agent [40] → workflows as tools       (every real customer, retiring)
        │
        ▼
  Draft card         ✅  tools add lines; the worker's Save tap is the only write
        │
        ▼
  Reply              ✅  send WhatsApp message back
```

v2 and classic share everything above and below the agent: ingress, identity gate, the draft card, the Save
tap, journal / undo, the toolbox tools and the backend handlers. The old chain (understanding → canonicalization
→ planner → workflows) is the **classic path (retiring)**, replaced module by module once a module passes the
v2 gate. See [AGENTS.md](./AGENTS.md) §0 and §4.

---

## Current Status

| Area | Status | Notes |
|---|---|---|
| Ingress, Identity Gate, Reply | ✅ | Signature verify, dedup, media, Postgres-backed identity |
| v2 agent + skills (general, materials) | ⚠️ test companies only | Live gate (>= 90% right, 0 wrong saves, reply time) **not passed**; needs `GEMINI_API_KEY` run |
| Classic path (agent [40] → workflows) | ✅ real customers | Retiring module by module; old code deleted only after a module passes in v2 |
| Draft card + Save tap + journal / undo | ✅ | The only write door, shared by both paths |
| LangGraph workflow runtime | dropped | The agent calls tools; there is no graph runtime to build |

---

## Folder Overview

```
src/
├── ingress/          M2 — webhook, dedup, normalization, media
├── agent_v2/         v2 — one agent + skills
│   ├── runner.py        V2Runner (eligibility, fallback, loop guard), ShadowRunner
│   ├── agents/main.py   MainAgent: context + rules + tools → one model run
│   ├── skills/general/      SKILL.md
│   └── skills/materials/    SKILL.md, tools.py, evals.yaml
├── runtime/          DI, lifecycle, message_journey (the assistant_mode switch), agent/ (classic agent, toolbox, draft card)
├── understanding/    classic path (retiring) — AI pipeline (speech, vision, extraction, confidence)
├── context/          context resolution
├── canonicalization/ classic path (retiring)
├── planner/          classic path (retiring)
├── workflows/        stub (empty); will not be built — v2 skills replace it
├── interactions/     stub (empty)
├── memory/           stub (empty)
├── backend/          Capability boundary — ports + one Postgres adapter
├── channel/          Outbound WhatsApp rendering
├── auth/             HTTP API — mobile app JWT login
├── admin/            HTTP API — organization admin endpoints
├── users/            HTTP API — tenant user CRUD
├── projects/         HTTP API — project and site management
└── main.py           ASGI entry point
```

To add an assistant feature: add a v2 skill (SKILL.md, tools.py, evals.yaml); see
[assistant-v2.md](../../docs/architecture/assistant-v2.md#how-to-add-a-feature).

---

## Key Architectural Decisions

These decisions are non-negotiable and explain why the codebase looks the way it does.

**Contracts first** — every module boundary is a Pydantic model in `shared/contracts/`. No module depends on another module's internals.

**Ports and adapters** — all I/O (DB, AI, cache, storage) is behind a Python `Protocol`. Fake adapters allow full testing without infrastructure. Real adapters are injected at startup.

**SQL belongs in exactly one file** — `backend/postgres/actor.py`. Nothing else in this service queries the database directly.

**AI providers are isolated in `platform/ai/`** — the assistant imports ports, never SDKs. Provider swaps require changing one adapter file.

**One agent, skills and tools** — an assistant feature is a v2 skill (rules in `SKILL.md`, tools, evals), never a new workflow, router or word list.

**Nothing saves without the Save tap** — the agent only puts lines on the draft card.

---

## Next

- Run the v2 live gate with `GEMINI_API_KEY` (>= 90% right, 0 wrong saves, reply time not worse than classic) and pick the model (control panel, Providers, "WhatsApp assistant v2").
- If it passes: move real companies to v2 one at a time (`assistant_mode`), then retire the classic route of each module.
- More skills as folders in `agent_v2/skills/`, each with evals.
- Longer-term, unchanged: conversation memory (pgvector), rules engine, rich WhatsApp reply templates; timeline (canonical events → project history feed).

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

*Last updated: 31 Oct 2026*
