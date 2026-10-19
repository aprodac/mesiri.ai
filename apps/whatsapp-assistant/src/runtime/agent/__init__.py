"""The assistant as a tool-calling agent (request [40]).

A model (Gemini, via the platform/ai port) reads a free-text or voice message,
decides which of the assistant's existing workflows to run -- each wrapped as a
thin tool -- and writes ONE reply from what the tools returned. No new
business logic lives here: every tool turns the model's arguments into the same
understanding the classic pipeline would have produced and runs it through that
pipeline (context, gates, planner, workflow, save-first), so validation, org
scoping and Labour/Attendance behaviour are exactly as before.

Modules:
- tools.py     the tool specs and argument -> understanding mapping (pure)
- toolbox.py   runs one tool call through a `WorkflowGateway`, tracks what was
               saved and whether the conversation is parked on a question
- prompt.py    the system instructions and the per-message context
- runner.py    the loop: limits, deadline, failure policy, the final reply
- gateway.py   the port to the existing pipeline + its message_journey wiring
- preset_pipeline.py  hands a tool's understanding to the existing journey

Switched per company by the `assistant_mode` setting (default off).
"""
