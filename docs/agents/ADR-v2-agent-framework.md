# ADR: v2 agent framework and pilot (request 174)

Status: accepted for the Materials pilot (1 Nov 2026). Owner approval: Ilan, in WhatsApp, request 174.
Decided in the team chat 31 Oct (#5982-#6059): go module by module, old and new side by side,
delete old code only after a module passes. Materials first (most wrong saves: split
Cement / സിമൻറ് stock, "176" when the stock is finished).

## What v2 is

One main agent that thinks, reads today's records, works through SKILLS and saves through ONE door:
a line on the draft card, written only by the Save tap (`runtime/agent/draft*.py`, unchanged).

```
message -> assistant_mode (company setting) ->
   classic      today's agent (default; nothing changes)
   v2_shadow    today's agent answers; v2 runs afterwards in the background, tools stubbed, logs a row
   v2_materials V2Runner: v2 reads the message first
                  took it   (card line / question / stock answer) -> reply composed by today's code
                  hand back / nothing to do / failed before acting -> today's agent, same turn
```

Code: `apps/whatsapp-assistant/src/agent_v2/` (`agents/main.py`, `skills/materials/{SKILL.md,tools.py,evals.yaml}`,
`runner.py`, `report.py`). The switch is `runtime/message_journey.py` (`_assistant_mode`, checked
right before `_run_agent`, same pattern as `_draft_v2_on`). Setting: `assistant_mode` in
`backend/.../organizations/settings.py` (`classic` | `v2_shadow` | `v2_materials`, superadmin-only,
unreadable = `classic`).

## Phase 0: framework spike (Google ADK vs google-genai tool calling)

Question: keep Google ADK only if it runs on our server without Vertex, fits our async runtime and
adds no reply time. Otherwise use google-genai tool calling directly.

Measured here (sandbox, 31 Oct, google-adk 2.13.0, google-genai 2.34.0, Python 3.11):

| Check | Result |
|---|---|
| Installs without Vertex / cloud credentials | yes (pip, 24 direct requirements) |
| Import time | 0.63 s once at start-up |
| Fits our async runtime | yes: `InMemoryRunner.run_async` inside asyncio, a function tool and a scripted model |
| Framework overhead per run (fake model, one tool round) | ~7 ms |
| Runs against the real Gemini API on our key | **not verified: no GEMINI_API_KEY in this environment** |

**Decision: google-genai tool calling through our existing `ToolCallingProvider`
(`platform/ai`, `run_tools`), not ADK.** Reasons:

1. ADK could not be verified live here (no key), and the spike's keep-condition includes the live
   reply time. The fallback in the plan applies.
2. The existing provider already carries what the pilot needs and what ADK would have to be
   taught: the deadline, the step limit, usage and failure reporting, the AI-outage mapping the
   turn already handles, and tool outcomes with `stop` / `done`. v2's tools run through the same
   `AgentToolbox` as today, so ADK's session, event and memory services would sit beside our draft
   store and journal as a second place for the same state ("one pipeline per decision").
3. No new dependency (24 packages) to deploy and patch for one skill.

Revisit when a second skill needs real multi-agent routing. The skill layout (`SKILL.md` + `tools.py`
+ `evals.yaml`) does not depend on the framework, so moving to ADK later changes `agents/main.py` only.

## Rules the code enforces (beyond what SKILL.md asks of the model)

- v2 only reads a plain message of a company on draft cards (`gateway.draft_mode`), never a tap, a
  waiting site question, a pending Yes / No, or a held photo. Those belong to today's agent.
- v2's tools are today's material tools under new names (`draft_receipt` = `save_material_receipt`,
  `draft_usage`, `draft_stock_count` = `adjust_stock`, `stock_for` = `query_materials`, `ask` =
  `ask_user`) and nothing else: no labour, work, issue, money tool is reachable. Their arguments are
  today's specs (a test holds that).
- A message is handled once. Any draft, question or stock answer by v2 means today's agent never
  runs for it (`hand_back` after a draft is refused; a failure after a draft is `degraded`, never a
  second pass). A hand-back, a run with no tool call, or a failure before any action runs today's
  agent in the same turn with the same arguments.
- Mixed messages (materials with labour, an issue, money...) are handed back WHOLE; v2 never drafts
  half of a message.
- Every number of the message must be on the card or asked about: a figure on no tool call and in no
  question is added to the reply as "I did not put 176 on the card. What is it for?" (English /
  Manglish / Hinglish senders; not yet worded for Malayalam script or Hindi senders).
- Time: v2 gets 9 s (today's agent 25 s) so a fallback stays inside one reply's budget. Shadow runs
  never on the reply path.

## Phase B: shadow

`v2_shadow`: after today's agent's reply is built, v2 runs as a background task with the draft tools
stubbed (nothing drafted, nothing saved, no catalog write) and writes one `journey_traces` row,
stage `agent_v2_shadow`, holding v2's proposed calls, today's calls, both timings. No new table, no
migration. `python3 scripts/v2_shadow_report.py --hours 24` prints the side by side
(`agent_v2/report.py`).

## Phase C: test company live (gate)

Set `assistant_mode = v2_materials` for the TEST company only
(`PUT /admin/organizations/{org_id}/settings`, platform admin). Gate, all of:

1. >= 90% right and **0 wrong saves** on the 30 new cases (`skills/materials/evals.yaml`) plus the 25
   of `tests/conversation/materials_golden.yaml`: `pytest -m live tests/agent_v2/test_evals.py`
   (needs `GEMINI_API_KEY`; set `GEMINI_MODEL` to compare a stronger model; prints accuracy, wrong
   saves, p50 / p95).
2. A live run by the team bot through `test_assistant`, shown in the group.
3. Reply time not worse than classic (compare p50 / p95 from the same run and the shadow rows).

A wrong save is a card line that must not be there, or has wrong figures. A message that should be
handed back and is drafted counts as one.

## Request 178: the five roots of the 31 Oct live test (12/21 right, 3 would-be wrong saves)

The live test showed v2 was mostly today's parts renamed. What changed, and where:

1. **Brain / budget.** `MAX_STEPS` 3 -> 6, `TIMEOUT_SECONDS` 9 -> 20 (a message v2 takes never also
   runs classic, so the room does not double a reply; only a hand-back, one quick round, or a failure
   before any action falls back to classic). The v2 model is settable on its own: `MESIRI_V2_MODEL`
   (the resolver's `run_tools(model=...)`; unset = the company's `agent` route, as classic). **The
   measurement is NOT done:** the build session had no `GEMINI_API_KEY`. To pick the brain run
   `GEMINI_MODEL=<model> pytest -m live tests/agent_v2/test_evals.py -s` for `gemini-2.5-flash`,
   the strongest Pro / newer model on the key, record accuracy, wrong saves and v2 / classic p50 and
   p95 in the table below, choose by accuracy then p95, set `MESIRI_V2_MODEL`.

   | model | right | wrong saves | v2 p50 / p95 | classic p50 / p95 |
   |---|---|---|---|---|
   | gemini-2.5-flash | not run | not run | not run | not run |
   | (strongest on the key) | not run | not run | not run | not run |

2. **Real v2 tools** (all through today's toolbox, so site resolver, unit gate, repeat check and
   card are the existing ones): `transfer` (-> `transfer_material`; no destination: `ask` for the
   DESTINATION), `change_line` (-> `update_pending_card` on the open card; a saved card by its id),
   `remove_line` (-> `remove_card_line`, new, built on `corrections.drop_from_open_card`, the one
   place that takes lines off a card; classic's typed removal now calls the same function),
   `material_request_not_available` ("cement venam": one fast line, no card, no second round).
   `draft_receipt` already took `unit_cost` / `supplier`; the card line now shows the rate
   (`interactions/saved_summary.py`). Units: the prompt says keep the unit as said; the shared unit
   gate still converts when the COMPANY has saved a conversion (it never guesses a size), keeping what
   was reported on the line: not changed here (shared with classic).
3. **Context.** The prompt lists all active materials with their aliases (`catalog_with_aliases`,
   read only: `list_aliases` in `repositories/materials.py`) and names the overlapping ones
   (Steel / TMT Steel Bars): two fit -> ask. Duplicates are listed for the owner, not merged.
4. **Number check.** Draft tools carry `figures_placed` and `unplaced` (figure + reason: "25 = the old
   figure replaced", "176 = what the app shows"). The code asks only about a figure neither placed
   nor explained (a reason is required); the account keys never reach the card line. Lookups carry no
   figure check.
5. **Gate before live.** `tests/agent_v2/test_evals.py` (live) now runs the 41 + 25 cases through v2
   AND today's agent on the same messages and fails unless >= 90% right, 0 wrong saves, v2 p95 <=
   classic p95. Without the key it is skipped, and the team bot's live re-run must not be asked for.
   A person adds the `v2` case to `.github/workflows/claude-ops.yml` golden-live
   (`v2) FILES="$T/../agent_v2/test_evals.py"`) and runs it with `gh workflow run`; bots never touch `.github`.

Small, same files: a stock answer names its site ("📍 Site B") or "All your sites"
(`JourneyGateway.read_scope`, set where `_reading_site` decides it). The stale "Not saved, because no
site was picked" after "cement venam" came from the request being held for a site question; v2 now
answers a request at once, so it is never held (classic's hold-then-notice is unchanged).

## Out of scope (separate approvals)

Real customers, deleting old code, material requests / orders, sector hierarchy, the groups
listener (designed in: its running day summary can become one more context line of
`MainAgent`; not built), other modules, Labour / Attendance / Payroll / Workforce.

## Known limits

- A stock count needs a sender who may adjust stock (today's rule in the toolbox); for others the
  count line is not made by either agent.
- (Request 178 replaced the old catalog line, which in fact held only the first 10 names without
  aliases.) The prompt now carries every active material (ceiling 400) with its aliases and a note of
  overlapping names; `catalog_match` stays for a word not in the line.
- One extra read per message: the `assistant_mode` setting, as `draft_v2` already does.

## Second round (request 178, live re-test 31 Oct: 12/15)

- Size/grade words ("1.5 sq mm", "12 mm", "M20", "4 inch") are specifications, not quantities: the
  figure check ignores them (`tools._SPEC`), and SKILL.md says so. Before, "2 box 1.5 sq mm wire" asked
  "what is 1.5 for?".
- "Every item reaches the card or a question": SKILL.md tells the model to draft the clear items and
  `ask` about the unclear one in the same turn (the wire's Electrical/Binding question was lost behind
  the switch line). Eval 142. Model behaviour: only the live gate proves it.
- "...and at all sites?": `site: "all sites"` is an explicit scope in `JourneyGateway._reading_site`
  (shared, read-only; classic gains the same). Two scopes in one message = two `stock_for` calls. Eval 143.
- Not changed: "5 load M sand = 10 cum" comes from a company-saved conversion (the built-in table has
  no load), so it is the company's own rule, not a guess. "1 box = how many rolls?" is the shared unit
  gate asking because wire is stocked in rolls; the v2 prompt now says never to ask it itself.

## Rollback

Set the company's `assistant_mode` to `classic` (instant), or delete the setting. Code: revert the
commits. No data migration; no existing record is touched.
