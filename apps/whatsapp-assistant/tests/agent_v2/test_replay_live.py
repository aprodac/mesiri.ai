"""Request 185: replay real conversations through an engine on the real model.

    python3 scripts/v2_replay.py fetch --days 5          # the corpus (read-only, outside the repo)
    MESIRI_REPLAY_CORPUS=~/.mesiri/replay/corpus.jsonl GEMINI_API_KEY=... \\
    MESIRI_REPLAY_ENGINE=v2 GEMINI_MODEL=gemini-2.5-flash \\
        pytest -m live apps/whatsapp-assistant/tests/agent_v2/test_replay_live.py -s

Prints production's numbers (what customers got) and the engine's on the same conversations,
and writes both, with every finding, to ~/.mesiri/replay/report-<engine>-<model>.txt. Gate for a
new engine: fewer severe findings than production and no conversation that got worse.
Skipped without GEMINI_API_KEY or a corpus.
"""

from __future__ import annotations

import os
import statistics
from pathlib import Path

import pytest
from tests.agent_v2.replaykit import V2Engine, replay

from agent_v2.replay import corpus as cp
from agent_v2.replay.checks import SEVERE, check_conversation
from agent_v2.replay.report import Scored, details, summary


def _engine(name: str, provider):  # noqa: ANN001, ANN202
    if name == "v2":
        return V2Engine(provider)
    if name == "adk":
        from tests.agent_v2.replaykit import AdkEngine  # request 185 step 2

        return AdkEngine(provider)
    raise ValueError(f"unknown engine {name!r} (v2 | adk)")


@pytest.mark.live
async def test_replay_real_conversations():
    key = os.environ.get("GEMINI_API_KEY")
    corpus_path = Path(os.environ.get("MESIRI_REPLAY_CORPUS", str(cp.DEFAULT_DIR / "corpus.jsonl"))).expanduser()
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    if not corpus_path.exists():
        pytest.skip(f"no corpus at {corpus_path}: run scripts/v2_replay.py fetch")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    engine_name = os.environ.get("MESIRI_REPLAY_ENGINE", "v2")
    limit = int(os.environ.get("MESIRI_REPLAY_LIMIT", "0")) or None
    provider = GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=model))
    which = os.environ.get("MESIRI_REPLAY_SPLIT", "holdout")  # the gate is judged on days fixes never saw
    conversations = cp.split(cp.load(corpus_path), which)[:limit]

    before, after, seconds, crashes = [], [], [], []
    for conv in conversations:
        turns = [t for t in conv.turns if t.replayable]
        before.append(
            Scored(conv.key, len(turns), check_conversation([t.text for t in turns], [t.reply for t in turns], [t.kind for t in turns]))
        )
        out = await replay(conv, _engine(engine_name, provider))
        after.append(Scored(conv.key, len(out.replies), out.findings))
        seconds += out.seconds
        crashes += [f"{conv.key} {e}" for e in out.errors]
        print(f"{conv.key}: production {len(before[-1].findings)} findings -> {engine_name} {len(after[-1].findings)}")

    worse = [a.key for b, a in zip(before, after, strict=True) if b.clean and not a.clean]
    report = "\n\n".join(
        [
            summary("production (what customers got)", before),
            summary(f"{engine_name} on {model} (replayed, split={which})", after),
            f"reply time p50 {statistics.median(seconds):.1f}s  max {max(seconds):.1f}s" if seconds else "",
            "conversations that got worse: " + (", ".join(worse) or "none"),
            "crashes:\n" + ("\n".join(crashes) or "none"),
            "findings (replayed):\n" + details(after, limit=1000),
            "NOTE: replayed in the test company (one site, test catalog), not the real company's sites and materials.",
        ]
    )
    out_path = cp.DEFAULT_DIR / f"report-{engine_name}-{model}-{which}.txt"
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"report -> {out_path}")
    severe_before = sum(1 for s in before for f in s.findings if f.check in SEVERE)
    severe_after = sum(1 for s in after for f in s.findings if f.check in SEVERE)
    assert not crashes, "the engine crashed on a real message"
    assert severe_after < severe_before, "the engine is not better than production on the same conversations"
