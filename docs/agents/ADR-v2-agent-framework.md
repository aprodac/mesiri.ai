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

## Out of scope (separate approvals)

Real customers, deleting old code, material requests / orders, sector hierarchy, the groups
listener (designed in: its running day summary can become one more context line of
`MainAgent`; not built), other modules, Labour / Attendance / Payroll / Workforce.

## Known limits

- A stock count needs a sender who may adjust stock (today's rule in the toolbox); for others the
  count line is not made by either agent.
- The catalog line carries the first 60 active materials; `catalog_match` reaches the rest (name,
  then alias). The material alias list itself is not in the prompt (no list-aliases read exists).
- One extra read per message: the `assistant_mode` setting, as `draft_v2` already does.

## Rollback

Set the company's `assistant_mode` to `classic` (instant), or delete the setting. Code: revert the
commits. No data migration; no existing record is touched.
