# The API agent (pilot, WA-119): one model + one SOP + the dashboard's API

> Asked by Ilan, 1 Nov 2026: *"one base prompted model, and just that. The rest is the same
> backend API calls the web dashboard uses, opened to the AI so it understands which to use when."*
> Status: **pilot, materials only, not wired to WhatsApp.** Tracker WA-119.

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
  one-line purpose). `build_tools(openapi)` turns each into a tool: path + query parameters + JSON
  body fields from the OpenAPI document, `$ref` inlined, `X | None` read as `X`. Every write tool
  also takes `summary`, the line the person confirms. A route missing from the API fails the build
  (and the test). **Adding a module = adding its routes to `ALLOWED`.**
- `client.py`: `ApiClient` calls the API with a bearer token for the sender. Two ways to get it:
  `Actor` (a 5-minute token made by the backend's own `create_access_token`, the same claims as the
  login) or `token=` (a token the person already has, from logging in). With `app=` the call goes
  through `httpx.ASGITransport` into the same FastAPI app (no network). With `base_url=` it goes
  over HTTP.
- `agent.py`: `ApiAgent.run` runs the model through the existing `ToolCallingProvider` port
  (Gemini today; only Gemini implements tool calling in `platform/ai`). It returns the model's reply
  and the held entries. `confirm(client, pending)` sends them in order, each with an
  `Idempotency-Key`. The API's own checks decide; a refusal comes back as it is.
- `scripts/api_agent_chat.py`: try it in a terminal against a running server with a dashboard
  login and a Gemini key (`--model gemini-2.5-pro` to compare models).

Pilot tools: `list_projects`, `list_sites`, `search_materials`, `list_units`, `stock_levels`,
`stock_check`, `list_receipts`, `list_usage`, `record_receipt`, `record_usage`, `record_transfer`.

## Safety

- **Nothing is written without the person's confirmation.** A write tool only records the entry
  and tells the model "ready, NOT saved"; `confirm` is the one place a write reaches the API.
- **Same access as the dashboard.** Every call carries the sender's token. The API's
  `get_auth_context` reloads the user, checks their status and project/site access, and binds the
  company (`bind_tenant`), exactly as for a dashboard request.
- **Only allowed routes.** A tool name not on `ALLOWED` is refused without a call.
- **Repeated confirmation records once** (`Idempotency-Key`, supported by inflows, outflows and
  transfers).

## Not done yet (next steps)

1. **Measure it**: real messages and voice-note transcripts from the test companies, through the
   API agent and through v2, same checks (`agent_v2/replay/checks.py`), on Flash and on Pro. Needs a
   working Gemini key (WA-111).
2. **WhatsApp wiring**: an `assistant_mode` value for the test companies, held entries kept per
   person between messages, a Save / Cancel button row from the summaries, sender to `Actor`.
   Making a token from a WhatsApp sender is security-sensitive: it needs Ilan's approval.
3. **Other modules**: labour (needs approval: Labour isolation), work, issues, expenses, site
   conditions, DPR: add their routes to `ALLOWED`.
4. **Gaps the API has and the assistant's path covers**: material aliases in `search_materials`
   (the API searches names), unit conversion asked in words, duplicate-delivery warning. Found by
   step 1, fixed in the backend so the dashboard gets them too.
