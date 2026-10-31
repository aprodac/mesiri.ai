"""Today's tool specs as ADK tools (request 185).

A ``SpecTool`` declares one ``ToolSpec`` (name, description, JSON schema: the same the
google-genai engine sends) and runs it through the run's shared handler
(``MainAgent.handler``). The handler's ``ToolOutcome`` keeps today's meaning:

- ``stop``: the run ends after this round (a question the user must answer first);
- ``done``: this call needs no words from the model; when every call of a round is done the
  run ends there too (the code writes the reply).

ADK has no per-call "end now", so the round's outcomes are kept in ``RunState`` and its
``before_model`` callback ends the run before the next model call, the way the provider loop
does. It also takes the tools away after ``max_steps`` rounds, so the model must answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.genai import types

from mesiri_ai.models import ToolCallRecord, ToolOutcome


@dataclass(slots=True)
class RunState:
    """One message's run: the handler, what each round decided, and the trace."""

    handle: Any
    max_steps: int
    records: list[ToolCallRecord] = field(default_factory=list)
    model_calls: int = 0
    #: Outcomes of the round in progress (reset when the model is called again).
    round: list[ToolOutcome] = field(default_factory=list)
    stop_reason: str = "answered"

    async def call(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        try:
            outcome = await self.handle(name, dict(args))
            error = None
        except Exception as exc:  # noqa: BLE001 -- told to the model, kept in the trace (as the provider loop)
            outcome = ToolOutcome(content={"error": "the tool failed"})
            error = f"{type(exc).__name__}: {exc}"
        self.records.append(ToolCallRecord(name=name, arguments=dict(args), outcome=outcome, error=error))
        self.round.append(outcome)
        return outcome

    def before_model(self, callback_context: Any, llm_request: LlmRequest) -> LlmResponse | None:
        """End the run when the last round said so; take the tools away after the last allowed round."""
        if self.round:
            if any(o.stop for o in self.round):
                self.stop_reason = "stopped_by_tool"
            elif all(o.done for o in self.round):
                self.stop_reason = "done_by_tools"
            if self.stop_reason != "answered":
                return LlmResponse(content=types.Content(role="model", parts=[]), turn_complete=True)
        self.round = []
        if self.model_calls >= self.max_steps + 1:
            self.stop_reason = "max_steps"
            return LlmResponse(content=types.Content(role="model", parts=[]), turn_complete=True)
        if self.model_calls >= self.max_steps and llm_request.config is not None:
            llm_request.config.tools = None  # the round after the last tool round: answer from what you have
            llm_request.tools_dict.clear()
        self.model_calls += 1
        return None


class SpecTool(BaseTool):
    """One ``ToolSpec`` as an ADK tool."""

    def __init__(self, spec: Any, state: RunState) -> None:
        super().__init__(name=spec.name, description=spec.description)
        self._parameters = spec.parameters
        self._state = state

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name, description=self.description, parameters_json_schema=self._parameters
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> Any:
        outcome = await self._state.call(self.name, args)
        return outcome.content
