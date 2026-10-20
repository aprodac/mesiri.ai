"""Capability help — answering "what can you do?" and "how do I ...?".

The WhatsApp assistant has 24 user-pickable workflows but only ever taught
users about the handful that happened to be written into a menu by hand. A
user who does not already know a capability exists has no way to discover
it, which is the core friction of a WhatsApp-first product: there is no UI
to browse.

This service turns a free-form question into the workflows that answer it.
It reads the same ``workflows/registry.py`` table every other discovery
surface renders from, so a workflow becomes answerable here on the day it
is registered -- there is no separate help document to maintain, and no way
for help to describe a capability that does not exist.

Layering: this lives in ``runtime/`` because it does I/O (one LLM call
behind ``JsonGenerationProvider``). It is deliberately *not* a workflow --
workflow nodes may not call AI or query anything (see the node docstrings
and the rule cited in ``inbound_journey/process.py``), so a help answerer
built as a graph could only format what someone else looked up. It is also
not in ``channel/replies.py``, which is pure rendering with no I/O. The
matched keys are handed to the renderer, matching how ``actor_profile`` is
injected for WHO_AM_I.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from mesiri_ai.ports.generation import JsonGenerationProvider
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.logging_ports import TraceLogger
from runtime.noop_loggers import NoopTraceLogger

logger = logging.getLogger(__name__)

# At most this many suggestions come back. Three is a picker; ten is the
# menu the user could already have opened by sending "menu", and offering
# ten "matches" is a way of saying nothing matched.
_MAX_MATCHES = 3

#: "capability" = asks what the bot can do / how to do something; "smalltalk" =
#: meta talk, chit-chat or a complaint about the bot. Anything else (including a
#: bad parse) is "capability", which is what every question got before.
KIND_CAPABILITY = "capability"
KIND_SMALLTALK = "smalltalk"


@dataclass(frozen=True)
class CapabilityAnswer:
    keys: tuple[WorkflowKey, ...] = ()
    kind: str = KIND_CAPABILITY


_SYSTEM_PROMPT = """You match a construction site worker's question to the assistant's capabilities.

You are given a CATALOGUE of everything the assistant can do. Each entry has a `key`, a `title`, a `description`, and `examples` of messages that trigger it.

Return the keys whose capability would answer the user's question, best first, at most {max_matches}.

RULES:
1. Only ever return keys that appear verbatim in the CATALOGUE. Never invent one.
2. Return [] if the question is not about what the assistant can do -- if it is small talk, a question about the construction work itself, or a report rather than a question. [] is the right answer far more often than a bad guess: an empty result shows the user the full menu, a wrong one sends them down the wrong path.
3. The user is asking HOW TO DO something or WHETHER something is possible. "How do I record a delivery?" matches the material receipt capability. "Can I undo a payment?" matches the reversal capability.
4. A broad question ("what can you do?", "help") returns [] -- that is answered with the full menu, not a guess at three capabilities.
5. Judge by meaning, not shared words. Users write in Indian English, transliterated Hindi/Malayalam, and mixed script, and voice notes arrive already translated but often clumsily.

6. Also classify the message as "kind": "capability" if the user asks what the assistant can do or how to do something; "smalltalk" if it is meta talk about the assistant ("are you hardcoded", "you sound like a bot"), chit-chat, or a complaint about the assistant. When unsure, use "capability".

Output JSON only, in this exact shape:
{{"keys": ["capability.key", "another.key"], "kind": "capability"}}
"""


def _catalogue(role: str | None) -> list[dict[str, object]]:
    """The capability catalogue as the model sees it, filtered to what this
    role may actually use -- so help never teaches someone a workflow whose
    role gate will refuse them (see WorkflowDefinition.allowed_roles)."""
    from workflows.registry import iter_user_initiable

    return [
        {
            "key": d.key.value,
            "title": d.title,
            "description": d.one_liner,
            "examples": list(d.examples),
        }
        for d in iter_user_initiable(role)
    ]


class CapabilityHelpService:
    """Matches a free-form question to registered workflows."""

    def __init__(
        self,
        json_generation: JsonGenerationProvider,
        *,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._json = json_generation
        self._trace_logger: TraceLogger = trace_logger or NoopTraceLogger()

    async def match(
        self,
        question: str,
        *,
        role: str | None = None,
        correlation_id: str = "",
    ) -> tuple[WorkflowKey, ...]:
        """Just the matched workflows; see :meth:`answer`."""
        return (await self.answer(question, role=role, correlation_id=correlation_id)).keys

    async def answer(
        self,
        question: str,
        *,
        role: str | None = None,
        correlation_id: str = "",
    ) -> CapabilityAnswer:
        """Workflows that answer ``question``, best first, possibly empty.

        Never raises. Help is the surface a confused user reaches for, so a
        provider timeout or a malformed completion must degrade to "here is
        the menu" rather than to an error -- the caller renders the full
        capability menu for an empty result, which is a good answer in its
        own right, not a failure state.
        """
        catalogue = _catalogue(role)
        if not catalogue:
            return CapabilityAnswer()

        t0 = time.perf_counter()
        try:
            raw = await self._json.generate_json(
                system_prompt=_SYSTEM_PROMPT.format(max_matches=_MAX_MATCHES),
                user_prompt=(
                    f"CATALOGUE:\n{json.dumps(catalogue, ensure_ascii=False)}\n\n"
                    f"QUESTION:\n{question}"
                ),
                correlation_id=correlation_id or None,
            )
        except Exception as exc:  # noqa: BLE001 -- see the docstring
            await self._log(correlation_id, t0, succeeded=False, exc=exc)
            logger.warning(
                "capability_help.match_failed correlation_id=%s", correlation_id, exc_info=True
            )
            return CapabilityAnswer()

        matches = self._parse(raw, role)
        await self._log(correlation_id, t0, succeeded=True, matched=len(matches))
        return CapabilityAnswer(matches, self._parse_kind(raw))

    @staticmethod
    def _parse_kind(raw: str) -> str:
        """"smalltalk" only when the completion says so plainly; a missing
        field or a bad parse is "capability", the behaviour before kinds."""
        try:
            kind = json.loads(raw).get("kind")
        except (json.JSONDecodeError, AttributeError, TypeError):
            return KIND_CAPABILITY
        return KIND_SMALLTALK if kind == KIND_SMALLTALK else KIND_CAPABILITY

    def _parse(self, raw: str, role: str | None) -> tuple[WorkflowKey, ...]:
        """Turn the completion into keys, dropping anything unrecognized.

        Every key is re-checked against the role-filtered catalogue rather
        than trusted from the model: a hallucinated key, or a real key the
        model saw in an earlier turn but that this role may not use, must
        not become a suggestion.
        """
        try:
            payload = json.loads(raw)
            raw_keys = payload["keys"] if isinstance(payload, dict) else payload
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("capability_help.unparseable_completion")
            return ()
        if not isinstance(raw_keys, list):
            return ()

        allowed = {entry["key"]: entry for entry in _catalogue(role)}
        seen: set[str] = set()
        matched: list[WorkflowKey] = []
        for candidate in raw_keys:
            if not isinstance(candidate, str) or candidate in seen or candidate not in allowed:
                continue
            seen.add(candidate)
            matched.append(WorkflowKey(candidate))
            if len(matched) == _MAX_MATCHES:
                break
        return tuple(matched)

    async def _log(
        self,
        correlation_id: str,
        t0: float,
        *,
        succeeded: bool,
        matched: int = 0,
        exc: Exception | None = None,
    ) -> None:
        """One trace row per call, same as every other provider call in the
        journey -- an unexplained multi-second gap in journey_traces is what
        made the interaction classifier's latency invisible (see
        interactions/llm_classifier.py)."""
        try:
            await self._trace_logger.log_stage(
                correlation_id=correlation_id,
                stage="capability_help",
                stage_payload={"matched": matched},
                duration_ms=int((time.perf_counter() - t0) * 1000),
                succeeded=succeeded,
                error_code=type(exc).__name__ if exc else None,
                error_message=str(exc) if exc else None,
            )
        except Exception:  # noqa: BLE001 -- tracing must never break a reply
            logger.debug("capability_help.trace_failed", exc_info=True)
