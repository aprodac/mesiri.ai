"""Request 185: v2 on Google ADK (Agent Development Kit) with real conversation memory.

``agent``   ``AdkAgent``: the v2 main agent run by ADK; same tools, handler, guards and reply
            code as ``agents.main.MainAgent`` (one code path), different engine and memory
``tools``   ``SpecTool``: one of today's tool specs as an ADK tool, run by the shared handler
``memory``  the conversation store: one session per person per day, every turn kept whole
            (their words, a swiped message, Mesiri's reply as sent, tool calls and results)
``models``  the model: Gemini through ADK with the key Mesiri already has; ``ScriptedLlm`` for tests

Why ADK and not the provider loop: the memory. Today the model sees a ≤400-char gist of each
earlier reply with every question removed (runtime/agent/history.py), so it denied its own
words and lost the question it had asked (docs/reviews/2026-10-31-v2-cross-check.md, family 1).
"""
