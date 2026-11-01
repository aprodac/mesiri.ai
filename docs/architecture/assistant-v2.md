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
  time not worse than classic. The live run needs `GEMINI_API_KEY` and has not been done:
  the 31 Oct runs scored 0% because the key (`TEAMMATE_GEMINI_API_KEY`) hit its monthly
  spending cap, which also blocks every deploy's live gate since then (tracker WA-111).
  Until it runs, v2 does not go to a real customer.

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

Today (request 185): `general` (every part of a message, feedback, unknown things, the words
they see), then one skill per module: `labour`, `work`, `issues`, `expenses`, `site` (weather,
plan, work site, engineer questions), `reports` (DPR, project status), and `materials` (its own
v2 tool names). The module skills use today's tools under their own names
(`skills/<module>/tools.py` lists them; `agents/main.py` reads the registry in
`skills/__init__.py`), so their rules moved from the classic prompt (which v2 never read) into
the skill files. Each has an `evals.yaml` (34 cases, the 27-31 Oct failure families and their
guards; `tests/agent_v2/test_module_skills_185.py`, live gate per module).
Not in v2 yet: photos and bill photos, documents, admin (classic until given a skill).

## Tools

| Group | Tools | Behind it |
|---|---|---|
| Materials (skill tools) | `draft_receipt`, `draft_usage`, `draft_stock_count`, `transfer`, `change_line`, `remove_line`, `answer_question`, `catalog_match`, `ask`, `material_request_not_available`, `stock_for` | the existing toolbox / draft card / `corrections.drop_from_open_card` |
| Other records (existing toolbox tools, unchanged) | `save_labour`, `save_work_done`, `save_expense`, `report_issue`, `update_issue`, `correct_work_quantity`, `note_for_engineer`, `set_site_conditions`, `request_dpr`, `set_work_site` | same specs, same draft card, same Save tap |
| Reads | `query_work_log`, `query_labour`, `query_project`, `query_expenses`, `query_open_needs`, `my_scope`, `stock_for` | read-only |

`change_line` (like classic `update_pending_card`) takes every figure a line shows: the
`_CHANGES` fields plus `counted`, `total_cost`, `unit_cost`, `to_site`, `issue_type`
(`tools.OPEN_CARD_ONLY_FIELDS`, request 193). A failed call's reason is kept in the
`agent_tools` trace (`vps-agent-trace`).

**Tool parity (request 194).** v2 takes every message of its companies (no hand-back), so a tool
only today's agent has is a feature those companies lose. `change_or_undo` / `undo_last` (take back
or correct something saved, any module) and `transfer_money` are v2 tools (skills `general`,
`expenses`). Still classic-only, each waiting for an owner decision and listed with its reason in
`tests/agent_v2/test_tool_parity_194.py` (a new gap fails it): **`request_material`** (classic sends a
"Material request" card to the engineer on Send; v2 says requests are not built), and the admin
tools (create site / project, members, join code). Questions go through `ask` with 2-3 options
(buttons) in every module (general SKILL "Asking: one tap, not typing").

Admin tools (create site / project, members, join code) stay with the classic agent. The labour
tools are called unchanged for the 2 test companies only; Labour, Attendance, Payroll and
Workforce rules and data paths are untouched.

## The save door

One door: a line on the **draft card** (`runtime/agent/draft*.py`), written only by the **Save
tap** (Cancel removes the lines). Every write tool goes through the existing toolbox, so the site
resolver, unit gate, repeat check, journal and undo are the ones classic uses. There is no new
write path in v2.

## Reply writing and honesty rules

**v2 writes its own reply (request 196, `agent_v2/reply.py`).** The model's words go out: the
greeting, every answer, every part of the message. The code only takes away what may not go out
(a claimed save / change / send, a figure in no source, an engineer promise no tool made, tool or
code words) and draws below them the lines, their questions, the system's lines and the buttons
(today's card functions). It never swaps the words for a template because they do not repeat the
lines: today's composer does that in four places (`_code_card`, `_one_sentence`, `_covering`,
`_natural`) and drops sentences off a word list (`without_stray_sentences`), which is what lost the
greeting, the weather answer and "who else reported" on 1 Nov. Today's agent keeps its composer
unchanged. Code-owned replies stay the code's: report-only, module off, equipment, a failed write,
a site question, and a turn where the model wrote nothing. v2's `ask` has no `other_parts`: a clear
record never waits behind a question.

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
- A read tool's template text is facts for the agent, never the reply; if a message asked a stock question and the agent did not look it up, the code looks it up and puts the answer under the reply (ADR, "Request 180, live re-test").
- **Card questions (request 184):** a line waiting on a question is answered with `answer_question` (typed, voice, or a button's text; same code as the tap, `draft_flow.answer_by_text`); `change_line` refuses a waiting line and says so. A failure on a card with open questions is worded by code from the card (`draft.open_questions_text`) with the card's buttons; never "send it again".
- A complaint about the last reply gets a short sorry, what will be different, and the part they
  actually asked for, never the same text again.

## Long mixed messages (request 195)

A round of calls that only put lines on the card ends the run without another model call (request
143, speed), but only when the message is plainly finished: every figure placed and one short
sentence (`agents/main.py`, `is_one_part`, at most 12 words). Otherwise the model gets the next round,
told what is still open (`MORE_TO_DO`), so a voice note with a greeting, a question, two receipts,
labour and "did anyone report" is done in one turn. Both engines (they share the handler).

## Engine and memory (request 185)

Two engines run the same agent (same tools, handler, rules, reply code):

- `v2`: google-genai tool calling through `ToolCallingProvider`; memory = the last 10 turns as
  gists (`runtime/agent/history.py`). Live on the 2 test companies.
- `v2_adk`: **Google ADK** (`agent_v2/adk/`); memory = the whole day's conversation per person
  in Postgres (`assistant_sessions` / `assistant_session_events`, migration 0496): what they said,
  the message they swiped, tool calls and results, the reply as sent. The day's state (open card,
  records, catalog) is in the instructions each turn, never in the conversation. Not on any
  company yet: it waits for the replay gate (below) on the real model.

Decision and details: ADR, section "Request 185".

## Replay test (request 185)

Real conversations, replayed and scored: `python3 scripts/v2_replay.py fetch --days 5` (read-only,
kept in `~/.mesiri/replay`, never committed), `baseline` scores what production answered, and
`tests/agent_v2/test_replay_live.py` replays them through `v2` or `v2_adk`
(`MESIRI_REPLAY_ENGINE`) on the real model with the same checks (`agent_v2/replay/checks.py`: dead
end, repeated question/reply, can't-see, unasked dump, no reply; card jargon, negative stock,
outage, trial limit counted). The newest day is held out: fixes are tuned on the other days and
the gate is judged on the held-out one, then on a fresh fetch.

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
= `classic` | `v2_shadow` | `v2` | `v2_adk`. **Rollback is instant:** set the company to `classic` (or
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
