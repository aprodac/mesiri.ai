"""Tool-calling port (request [40]).

A model that can call the caller's tools and write the final answer, behind
the same provider boundary as every other AI capability: the caller hands in
the conversation, the tool specs and one async handler that runs a tool;
the adapter owns the provider's function-calling protocol, the step limit,
the deadline, usage reporting and failure mapping.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable

from ..models import ChatMessage, ToolOutcome, ToolRunResult, ToolSpec

#: ``(tool_name, arguments) -> outcome``. Must not raise for a bad call: return
#: an outcome whose content says what was wrong, so the model can correct it.
#: An exception is recorded on the call and reported to the model as an error.
ToolHandler = Callable[[str, dict], Awaitable[ToolOutcome]]


@runtime_checkable
class ToolCallingProvider(Protocol):
    async def run_tools(
        self,
        system_prompt: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        handler: ToolHandler,
        *,
        max_steps: int = 3,
        timeout_seconds: float | None = None,
        correlation_id: str | None = None,
    ) -> ToolRunResult:
        """Run the model until it answers, a tool stops it, or ``max_steps``
        rounds of tool calls have run. Raises a ``MesiriError`` when the
        provider fails or the overall deadline passes."""
        ...
