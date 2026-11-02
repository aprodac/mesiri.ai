# Runtime flow

> The assistant's architecture is **v3: one model + one SOP + the dashboard's API as tools** (locked
> 2 Nov 2026). The full document is [assistant-v3.md](assistant-v3.md); this page is the short flow.

```
WhatsApp message -> ingress -> identity gate -> journey (signup, trial, sender checks)
   -> assistant_mode:  api (v3: facts up front, one model, API routes as tools)  <- test companies; the direction
                       classic (today's agent [40] -> workflows)                  <- real customers until moved
   -> v3: GET answers at once; POST / PATCH wait in the ready list -> ONE Save -> the API, as the sender
   -> classic: draft card -> Save -> records written
```

**Save rule:** nothing is written until the worker taps **Save**; **Cancel** removes what was
prepared. This holds in v3 and classic. v2 was removed (WA-134).

**Status:** real customers run classic until they are moved to v3 one at a time (WA-137); then
classic is deleted (WA-138).

The earlier direction note (classifier -> planner -> workflow graph moving to "one AI + tools") is
in [ADR-assistant-agent-wrap-not-rebuild.md](ADR-assistant-agent-wrap-not-rebuild.md) (historical).
