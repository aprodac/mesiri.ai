"""The assistant as a tool-calling agent (request [40]).

A model (Gemini, via the platform/ai port) reads every message (text, voice,
or a photo/document described by the vision model), decides which of the
assistant's workflows to run -- each wrapped as a thin tool -- and writes ONE
reply from what the tools returned. No new business logic lives here: each
tool's arguments go to a direct entry that settles the sender's context,
reuses the field normalisers and seed functions, and starts the unchanged
workflow (save-first, validation, org scoping and Labour/Attendance rules as
before).

Modules:
- tools.py          the tool specs and argument -> candidate mapping (pure)
- toolbox.py        runs one tool call through a `WorkflowGateway`, tracks what
                    was saved and whether the conversation is parked on a question
- prompt.py         the system instructions and the per-message context
- runner.py         the loop: limits, deadline, failure policy, the final reply
- gateway.py        the port the toolbox calls
- journey_gateway.py  its implementation: tool -> entry -> workflow -> save
- entry_base.py     context, module switch, project/site for every entry
- material_entry.py, site_entry.py, labour_entry.py, query_entry.py  the entries

Every message runs through it (ARCH-06, 22 Oct 2026: the classic pipeline is gone).
"""
