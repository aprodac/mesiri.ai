# whatsapp-assistant: how to fix things here

The root `CLAUDE.md` governs process (phases, verification, git, approvals). This folder also
follows the fix approach set by Ilan on 29 Oct 2026: fix the class of failure at its root, check the
siblings and the end-to-end UX, never a one-off patch.

@../../docs/engineering/FIX_APPROACH.md

The assistant is v2: one agent + skills + tools. Read [assistant-v2.md](../../docs/architecture/assistant-v2.md) and the skill rule files (`src/agent_v2/skills/*/SKILL.md`) before changing assistant behaviour. A feature is a skill (SKILL.md + tools.py + evals.yaml); never a new workflow, router or word list.
