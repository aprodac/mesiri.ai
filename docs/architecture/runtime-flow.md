# Runtime flow

## Direction

The WhatsApp assistant's conversation layer is moving from a fixed pipeline (classify ->
canonicalize -> planner -> workflow graph -> reply templates) to one AI with a base prompt plus
tools, where the existing save/query code becomes the tools. See
[ADR-assistant-agent-wrap-not-rebuild.md](ADR-assistant-agent-wrap-not-rebuild.md), section
"Direction: one AI with a base prompt + tools" (accepted by Ilan, 20 Oct 2026; pilot pending).

**Save rule (WA-35, agent mode):** the agent's records are drafts until the worker taps
**Save** on its reply; **Cancel** removes them. See the ADR, section "10. The save rule".
