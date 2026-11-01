# The API agent (pilot, WA-119): one model + one SOP + the dashboard's API

> Asked by Ilan, 1 Nov 2026: *"one base prompted model, and just that. The rest is the same
> backend API calls the web dashboard uses, opened to the AI so it understands which to use when."*
> Status: **live behind `assistant_mode = "api"`; migration 0497 puts both test companies on it**
> (Mesiri Test Builders, Paraclette; applied by the next deploy). WA-119 / WA-121 / WA-122.
> Not measured on the real model (Gemini key cap, WA-111).

## The idea

```
message ──> one model + SOP.md ──> tools = the app's own API routes (from its OpenAPI)
                │                     GET  -> runs at once, as the sender
                │                     POST -> held, shown to the person
                └─> its own reply     confirm -> the held entries are sent to the API
```

There is one set of business rules, in the backend, used by the dashboard and the AI alike.
The AI is one more client of the API, acting as the person who sent the message, with that
person's access.

| | Classic | v2 | API agent |
|---|---|---|---|
| Understands the message | code (classifier, planner, word lists) | one agent + skill rules | one agent + one SOP |
| Saves through | the assistant's workflows | the assistant's toolbox (classic's save path) | **the backend API, as the dashboard** |
| Code around the model | a lot | reply guards, number guard, early stop | none: writes wait for confirmation |

Why: the industry guidance (Anthropic, "Building effective agents"; IBM Research on REST APIs as
agent tools) is to give a capable model clearly described tools and add complexity only when it
is shown to be needed, and to confirm writes with a person. The assistant's own save path
duplicates the backend's rules, which is where most per-scenario fixes came from.

## Code

`apps/whatsapp-assistant/src/agent_api/`

- `SOP.md`: the whole prompt. Principles, no scenarios.
- `tools.py`: `ALLOWED` is the list of API routes the agent may use (short name, method, path,
  one-line purpose, plus fields to `hide` or keep `fixed`, e.g. an expense's `source`). `build_tools(openapi)`
  turns each into a tool: path + query parameters + JSON body fields from the OpenAPI document,
  `$ref` inlined, `X | None` read as `X`. Every write tool also takes `confirm_line`, the line the
  person confirms. A route missing from the API, or a body field named `confirm_line`, fails the
  build (and the test). **Adding a module = adding its routes to `ALLOWED`.**
- `app.py`: the API the agent calls inside the worker (WhatsApp messages are handled by the ARQ
  worker, which has no web app): the same routers the live app mounts for those paths
  (`API_ROUTERS`; `/projects` is the assistant's own `projects.router`, as in `runtime/lifecycle.py`),
  on the worker's database pool. A test checks every tool route resolves to the same endpoint as
  in the live app.
- `client.py`: `ApiClient` calls the API with a bearer token for the sender. `Actor`: a 5-minute
  token made by the backend's own `create_access_token` with the login's claims, or `token=`: a
  token the person already has. In process (`app=`, `httpx.ASGITransport`, each call in its own
  task so the API's company binding never leaks into the caller) or over HTTP (`base_url=`).
- `agent.py`: `ApiAgent.run` runs the model through the existing `ToolCallingProvider` port,
  capability `api_agent` (control panel row "WhatsApp API agent"; unset = the `agent` model). GETs
  run at once; writes are held. Entries already waiting are listed in the prompt, and two tools act
  on them: `save_ready_entries` (only when the person says so; the API's answer goes back to the
  model) and `drop_ready_entries` (cancel, or drop-and-prepare for a correction). `confirm`
  sends entries with an `Idempotency-Key`.
- `whatsapp.py`: `ApiWhatsApp.handle(message, ctx)`, called by `runtime/message_journey.py` right
  after the sender and company are resolved and checked (unknown number, suspended company and
  trial cap keep their own replies) when the company's `assistant_mode` is `api`. Text and voice
  (transcribed first) go to the agent; a photo or document returns `False` and the journey carries
  on as before. Per person in Redis for a day: the last 12 turns and the waiting entries. A reply
  with entries waiting lists them under the model's words with **Save / Cancel** buttons (ids carry a
  batch id, so an older list's button does nothing). Save sends them as the sender; a refused one
  stays waiting with the API's reason. Every turn is traced (`agent_api_turn`, event source
  `agent_api`): tool calls, saves, what is waiting.
- `scripts/api_agent_chat.py`: try it in a terminal against a running server with a dashboard
  login and a Gemini key (`--model gemini-2.5-pro` to compare models).

Tools (28): projects and sites; `day_summary` and `timeline` (what was reported, by whom);
materials (catalog, units, stock, receipts, usage; record receipt / usage / transfer); labour
(attendance, worker register, **record attendance**); work (progress, **record work done**); issues
(list, report, resolve); expenses (list, categories, money accounts, record); a site's day (read;
set weather / hours lost / site working / tomorrow's plan); send the project DPR now.

**Two new API endpoints (WA-122), for the dashboard and the agent alike:**
`POST /labour/attendance` and `POST /progress/activities`. They run the same save handlers as a
WhatsApp confirmation (`ExecuteConfirmedLabourAttendanceHandler.execute`,
`ExecuteConfirmedCreateActivityHandler.execute`: `handle(confirmed)` now builds the command and
calls `execute`), so totals, cost, DPR and timeline read them the same way. Access is checked as
the other writes do; the site must belong to the project and company; a `worker_id` must be the
company's. The client's `Idempotency-Key` is turned into a UUID scoped to the company
(`domains/shared/execution.py`): a retry replays (200), two companies' keys never meet. 201
recorded, 422 refused with the handler's reasons.

**The API now lists its valid values** (WA-120, the same class of gap in four places): issue type
and severity, weather and site working (full / half / none), hours lost (0-24), and material
movement reasons are shown as `enum`s in the OpenAPI schema. Validation is unchanged. The dashboard's
API docs and the agent both see the choices instead of guessing.

## Safety

- **Nothing is written without the person's confirmation.** A write tool only records the entry
  and tells the model "ready, NOT saved"; `confirm` is the one place a write reaches the API.
- **Same access as the dashboard.** Every call carries the sender's token. The API's
  `get_auth_context` reloads the user, checks their status and project/site access, and binds the
  company (`bind_tenant`), exactly as for a dashboard request.
- **Only allowed routes.** A tool name not on `ALLOWED` is refused without a call.
- **Repeated confirmation records once** (`Idempotency-Key`, supported by inflows, outflows and
  transfers). The API stores the key scoped by company (`idempotency_uuid(org, key)`, BE-52), so
  two companies sending the same key never share a result.

## Switching a company on and off

`assistant_mode` = `api` (company setting; `PUT /admin/organizations/{org_id}/settings`, platform admin).
Migration 0497 sets it for the two test companies (downgrade: back to `v2`, only where it still
reads `api`). Rollback is instant: set it back (`v2` / `classic`). No data migration; records written through it
are ordinary dashboard records.

## Not done yet

1. **Measure it**: real messages and voice-note transcripts from the test companies, through the
   API agent and through v2, same checks (`agent_v2/replay/checks.py`), on Flash and on Pro. Needs a
   working Gemini key (WA-111).
2. Photos and documents (bills, attendance sheets) stay on the journey's existing path.
3. **Gaps the API has and the assistant's path covers**: material aliases in `search_materials`
   (the API searches names), unit conversion asked in words, duplicate-delivery warning, the morning
   site question. Found by step 1, fixed in the backend so the dashboard gets them too.
