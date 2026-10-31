# Runtime flow

> The assistant's architecture is **v2: one agent + skills + tools**. The full document is
> [assistant-v2.md](assistant-v2.md); this page is the short flow.

```
WhatsApp message -> ingress -> identity gate -> journey (taps / waiting questions keep their handlers)
   -> assistant_mode:  classic (today's agent [40] -> workflows, real customers, retiring)
                       v2_shadow (classic answers, v2 logs a row)
                       v2 (the agent reads, calls tools, writes the reply)  <- 2 test companies today
   -> draft card -> reply -> worker taps Save -> records written
```

**Save rule:** the agent's records are drafts until the worker taps **Save** on its reply; **Cancel**
removes them. This holds in v2 and classic. See [ADR-draft-per-message.md](ADR-draft-per-message.md).

**Status:** v2's live gate (>= 90% right, 0 wrong saves) is not passed; real customers run classic.

The earlier direction note (classifier -> planner -> workflow graph moving to "one AI + tools") is
in [ADR-assistant-agent-wrap-not-rebuild.md](ADR-assistant-agent-wrap-not-rebuild.md) (historical).
