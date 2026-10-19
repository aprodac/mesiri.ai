"""Deterministic fake providers (M3).

Used by the default test suite so no path calls a paid external API. Each fake
returns a preset result or raises a preset exception, and can be given a delay to
exercise timeout handling. They implement the same ports as the real adapters.
"""

from __future__ import annotations

import asyncio

from .models import (
    DecompositionResult,
    ExtractionResult,
    SpeechResult,
    TranslationResult,
    VisionResult,
)


class FakeSpeechProvider:
    def __init__(
        self,
        result: SpeechResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._result = result
        self._error = error
        self._delay = delay_seconds
        self.calls = 0

    async def transcribe(
        self, audio: bytes, *, language_hint: str | None = None, correlation_id: str | None = None
    ) -> SpeechResult:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        assert self._result is not None, "FakeSpeechProvider needs a result or an error"
        return self._result


class FakeVisionProvider:
    def __init__(
        self,
        result: VisionResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._result = result
        self._error = error
        self._delay = delay_seconds
        self.calls = 0

    async def analyze_image(
        self,
        image: bytes,
        *,
        mime_type: str | None = None,
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> VisionResult:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        assert self._result is not None, "FakeVisionProvider needs a result or an error"
        return self._result


class FakeExtractionProvider:
    provider = "fake"

    def __init__(
        self,
        result: ExtractionResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._result = result
        self._error = error
        self._delay = delay_seconds
        self.calls = 0
        self.last_semantic_hint: str | None = None
        self.last_expense_categories: list[str] | None = None
        self.last_text: str | None = None

    async def extract(
        self,
        text: str,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> ExtractionResult:
        self.calls += 1
        self.last_semantic_hint = semantic_hint
        self.last_expense_categories = expense_categories
        self.last_text = text
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        assert self._result is not None, "FakeExtractionProvider needs a result or an error"
        return self._result


class FakeDecompositionProvider:
    """Fake for DecompositionProvider.decompose() -- mirrors
    FakeExtractionProvider's shape exactly."""

    provider = "fake"

    def __init__(
        self,
        result: DecompositionResult | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self._result = result if result is not None else DecompositionResult()
        self._error = error
        self.calls = 0
        self.last_text: str | None = None

    async def decompose(
        self, text: str, *, correlation_id: str | None = None
    ) -> DecompositionResult:
        self.calls += 1
        self.last_text = text
        if self._error is not None:
            raise self._error
        return self._result


class FakeVoiceExtractionProvider:
    """Fake for VoiceExtractionProvider.understand_voice() -- the merged
    transcribe+extract call for voice. Mirrors FakeExtractionProvider's
    shape/tracking, since callers pass the same preset ExtractionResult
    (now carrying transcript/translated_text too)."""

    provider = "fake"

    def __init__(
        self,
        result: ExtractionResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._result = result
        self._error = error
        self._delay = delay_seconds
        self.calls = 0
        self.last_semantic_hint: str | None = None
        self.last_expense_categories: list[str] | None = None

    async def understand_voice(
        self,
        audio: bytes,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> ExtractionResult:
        self.calls += 1
        self.last_semantic_hint = semantic_hint
        self.last_expense_categories = expense_categories
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        assert self._result is not None, "FakeVoiceExtractionProvider needs a result or an error"
        return self._result


class FakeTranslationProvider:
    provider = "fake"

    def __init__(
        self,
        result: TranslationResult | None = None,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._result = result
        self._error = error
        self._delay = delay_seconds
        self.calls = 0

    async def translate_to_english(
        self, text: str, *, correlation_id: str | None = None
    ) -> TranslationResult:
        self.calls += 1
        if self._delay:
            import asyncio

            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return TranslationResult(
            translated_text=text,
            detected_language="FakeLang",
            model="fake",
            latency_ms=10.0,
        )


class FakeToolCallingProvider:
    """Scripted stand-in for a tool-calling model.

    ``script`` is a list of steps, one per model turn: a step is either a list
    of ``(tool_name, arguments)`` calls, or a string (the final answer). Calls
    go through the real handler, so adapters are exercised exactly as with a
    live model; only the model's choices are fixed. A callable step receives
    the results so far and returns a step (for answers built from tool output).
    """

    provider = "fake"

    def __init__(
        self,
        script: list,
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._script = list(script)
        self._error = error
        self._delay = delay_seconds
        self.calls = 0
        self.last_system_prompt: str | None = None
        self.last_messages: list = []

    async def run_tools(
        self,
        system_prompt,
        messages,
        tools,
        handler,
        *,
        max_steps: int = 3,
        timeout_seconds: float | None = None,
        correlation_id: str | None = None,
    ):
        from .models import ToolCallRecord, ToolOutcome, ToolRunResult

        self.calls += 1
        self.last_system_prompt = system_prompt
        self.last_messages = list(messages)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        known = {t.name for t in tools}
        records: list[ToolCallRecord] = []
        steps = 0
        for scripted in self._script:
            step = scripted(records) if callable(scripted) else scripted
            if isinstance(step, str):
                return ToolRunResult(
                    text=step, calls=records, steps=steps, stop_reason="answered", model="fake"
                )
            if steps >= max_steps:
                return ToolRunResult(
                    calls=records, steps=steps, stop_reason="max_steps", model="fake"
                )
            steps += 1
            stop = False
            for name, arguments in step:
                if name not in known:
                    outcome = ToolOutcome(content={"error": f"unknown tool {name}"})
                else:
                    outcome = await handler(name, dict(arguments))
                records.append(ToolCallRecord(name=name, arguments=dict(arguments), outcome=outcome))
                stop = stop or outcome.stop
            if stop:
                return ToolRunResult(
                    calls=records, steps=steps, stop_reason="stopped_by_tool", model="fake"
                )
        return ToolRunResult(calls=records, steps=steps, stop_reason="max_steps", model="fake")
