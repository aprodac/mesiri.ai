# whatsapp-assistant: how to fix things here

The root `CLAUDE.md` governs process (phases, verification, git, approvals). This folder also
follows the fix approach set by Ilan on 29 Oct 2026: fix the class of failure at its root, check the
siblings and the end-to-end UX, never a one-off patch.

@../../docs/engineering/FIX_APPROACH.md

The assistant is v3 (locked 2 Nov 2026): one model + one SOP + the dashboard's own API as tools. Read [assistant-v3.md](../../docs/architecture/assistant-v3.md) and `src/agent_api/SOP.md` before changing assistant behaviour. A feature is an API route in `src/agent_api/tools.py` `ALLOWED` (the dashboard gets it too) plus, when needed, a rule in `SOP.md`, with a scripted test in `tests/agent_api/`; never a new workflow, router or word list. v2 is removed; classic (`src/runtime/agent/`, workflows) serves real customers until they move, and gets no new features.
