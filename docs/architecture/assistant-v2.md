# The WhatsApp assistant, v2: one agent + skills + tools

> The one architecture document for the assistant. Decisions and history of v2 are in
> [ADR-v2-agent-framework.md](ADR-v2-agent-framework.md). Everything older (classifier, planner,
> workflow graphs, "wrap not rebuild") is **classic / retiring**, see [Status](#status-today).

## What v2 is

**One agent reads every message, decides what it holds, and writes its own reply.** It works
through **skills**: a skill is a folder with `SKILL.md` (the rules, in plain English),
`tools.py` (what the agent may call) and `evals.yaml` (cases that prove the rules work). The old
code is not rebuilt: the existing save/read code (`AgentToolbox` tools, the draft card, the Save
tap, journal / undo, the backend handlers) is used **only as tools** the agent calls.

**Nothing saves without the Save tap.** The agent's tools add lines to a draft card; the
supervisor's tap on Save is the only thing that writes records.

## Status today

- v2 is live **only on the 2 test companies** (Mesiri Test Builders and the Paraclette test
  company): the company setting `assistant_mode = v2` (set by migration 0495).
- **Real customers run the classic path**: today's agent (request [40]) which calls the old
  workflows as tools.
- v2's **live gate is not passed yet**: >= 90% right and 0 wrong saves on the eval sets, reply
  time not worse than classic. The live run needs `GEMINI_API_KEY` and has not been done.
  Until it is, v2 does not go to a real customer.

## Message flow

```
WhatsApp message
   -> ingress (webhook, dedupe, media, voice -> text)
   -> message_journey: taps, site questions, pending Yes / No, held photos (these keep their own handlers)
   -> assistant_mode (company setting, read right before the agent runs)
        classic     today's agent [40] -> workflows as tools      (default; every real customer)
        v2_shadow   classic answers; v2 runs afterwards in the background, tools stubbed, logs a row
        v2          V2Runner -> the v2 agent reads the message, calls tools, writes the reply
                       v2 fails BEFORE any action (a model outage) -> classic answers the same turn
                       v2 fails AFTER a line is on the card -> "degraded": say what is on the card, no second pass
   -> reply (card lines drawn by code, the agent's words around them) -> WhatsApp
   -> worker taps Save -> the card's lines are written (Cancel removes them)
```

`v2_materials` is the older name of `v2` and is still read as `v2`. An unset or unreadable
setting is `classic`. v2 reads only a plain text or voice message of a company on draft cards;
a tap, a waiting site question, a pending Yes / No or a held photo is not for it.

Code: `apps/whatsapp-assistant/src/agent_v2/` (`runner.py` the switch-side runner, `agents/main.py` the
agent, `skills/`, `report.py` the shadow report). The switch is `runtime/message_journey.py`
(`_assistant_mode`).

## What the agent knows (its context)

Built per message: the sender's sites and role, today's saved records, the open card, the last 10
turns **including Mesiri's own replies**, the material catalog with aliases (names that overlap
are flagged: two fit -> ask), and the rule files of every skill. Reading more is done with the
read tools, not by stuffing the prompt.

## Skills layout

```
agent_v2/skills/<skill>/
    SKILL.md     the rules in plain English (what to do, what to ask, what never to do)
    tools.py     tool specs the agent may call; reuses existing write paths
    evals.yaml   input message(s) -> expected tool calls / reply facts; a "must not save" case counts
```

Today: `skills/general` (every part of a message, feedback and complaints, questions, unknown
things: be honest and offer) and `skills/materials` (receipts, usage, stock counts, transfers,
line changes, stock questions).

## Tools

| Group | Tools | Behind it |
|---|---|---|
| Materials (skill tools) | `draft_receipt`, `draft_usage`, `draft_stock_count`, `transfer`, `change_line`, `remove_line`, `catalog_match`, `ask`, `material_request_not_available`, `stock_for` | the existing toolbox / draft card / `corrections.drop_from_open_card` |
| Other records (existing toolbox tools, unchanged) | `save_labour`, `save_work_done`, `save_expense`, `report_issue`, `update_issue`, `correct_work_quantity`, `note_for_engineer`, `set_site_conditions`, `request_dpr`, `set_work_site` | same specs, same draft card, same Save tap |
| Reads | `query_work_log`, `query_labour`, `query_project`, `query_expenses`, `query_open_needs`, `my_scope`, `stock_for` | read-only |

Admin tools (create site / project, members, join code) stay with the classic agent. The labour
tools are called unchanged for the 2 test companies only; Labour, Attendance, Payroll and
Workforce rules and data paths are untouched.

## The save door

One door: a line on the **draft card** (`runtime/agent/draft*.py`), written only by the **Save
tap** (Cancel removes the lines). Every write tool goes through the existing toolbox, so the site
resolver, unit gate, repeat check, journal and undo are the ones classic uses. There is no new
write path in v2.

## Reply writing and honesty rules

The agent writes the reply in the sender's language. The code keeps the guarantees, by composing
with the same code as classic replies:

- Never claim something is saved or changed (only the Save tap does that); the card lines are
  drawn by code, not by the model.
- **Number guard:** every figure of the message must be on the card or asked about. A figure on no
  tool call and in no question is added as "I did not put 176 on the card. What is it for?"
  (worded for English / Manglish / Hinglish; not yet for Malayalam script or Hindi). Size and
  grade words (1.5 sq mm, M20, 12 mm) are specifications, not quantities.
- No promise to tell the engineer unless the message asked for it and the tool did it.
- Unknown or unbuilt things (for example "cement venam", a material request): say so plainly
  and offer what is possible; no card, no invented answer.
- **Loop guard:** a words-only reply identical to the previous one to the same sender within 10
  minutes is replaced by "that is what I just said, tell me again in a few words".
- A complaint about the last reply gets a short sorry, what will be different, and the part they
  actually asked for, never the same text again.

## Model choice

The control panel, **Providers** page, has a row **"WhatsApp assistant v2"** (capability
`agent_v2`: model + fallback model, audited, no deploy). Unset, v2 uses the `agent` row (the
classic assistant's). `MESIRI_V2_MODEL` still wins over both. Budget per run: 6 tool rounds, 20 s.
Framework: google-genai tool calling through the existing `ToolCallingProvider` (not ADK; reasons
in the ADR). The model comparison is **not measured yet** (no key in the build sessions); numbers
go into the ADR table.

## Evals and the live gate

`evals.yaml` of each skill plus `tests/conversation/materials_golden.yaml` and
`general_messages.yaml`. Run: `GEMINI_MODEL=<model> pytest -m live tests/agent_v2/test_evals.py -s`
(needs `GEMINI_API_KEY`; skipped without it). **Gate, all of:** >= 90% right; **0 wrong saves** (a
card line that must not be there, or has wrong figures); v2 p95 reply time not worse than classic;
then a live run by the team bot, shown in the group. A message that should not be drafted and is
counts as a wrong save.

## The switch and rollback

Per company: `PUT /admin/organizations/{org_id}/settings` (platform admin) with `assistant_mode`
= `classic` | `v2_shadow` | `v2`. **Rollback is instant:** set the company to `classic` (or
delete the setting). No data migration; no record is touched; code rollback is a revert.

## Retirement plan (module by module)

Old and new run side by side. **Old code is deleted only after a module passes the gate in v2**,
never before, and never all at once.

| Module | v2 today | Old code that goes once it passes |
|---|---|---|
| Materials | skill built; on test companies; gate not passed | classic material workflow handlers and their word lists |
| Other records (labour, work, expense, issue, site notes, DPR) | called through the existing tools for the test companies | the classic route into those workflows (the tools themselves stay: v2 uses them) |
| Questions / reads | read tools | classic lookup route |
| Photos / documents, admin tools | not in v2 | stay classic until given a skill |

What is **kept** whatever happens: the draft card, the Save tap, journal / undo, the toolbox
tools, the backend handlers. They are the tools.

## How to add a feature

1. Make a skill folder `agent_v2/skills/<name>/` (or extend an existing one).
2. `SKILL.md`: the rules in plain English: when to call what, what to ask, what never to do.
3. `tools.py`: tool specs that **reuse the existing write paths** (toolbox / draft card / backend
   handler). Writes go to the draft card; reads are read-only.
4. `evals.yaml`: cases for the happy path, the ask-first path, and at least one "must not save".
5. Run the evals; a skill is not live until the gate passes.

**Never add a new workflow, router, classifier or word list.** If the agent gets something wrong,
fix it where [FIX_APPROACH](../engineering/FIX_APPROACH.md) says (rule in `SKILL.md` first), and
add the eval case.

## Related

- [ADR-v2-agent-framework.md](ADR-v2-agent-framework.md): decisions, measurements, requests 174 / 176 / 178 / 180
- [runtime-flow.md](runtime-flow.md): the short flow
- [apps/whatsapp-assistant/AGENTS.md](../../apps/whatsapp-assistant/AGENTS.md): code rules and the classic path (retiring)
- [ADR-draft-per-message.md](ADR-draft-per-message.md): the draft / Save parts are still valid in v2
