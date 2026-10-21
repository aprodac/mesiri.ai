"""Loader for general_messages.yaml (one JSON object per line, no YAML dependency)."""

from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).with_name("general_messages.yaml")


def load_cases() -> list[dict]:
    cases = []
    for line in PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- {"):
            cases.append(json.loads(line[2:]))
    return cases


SEQUENCES_PATH = Path(__file__).with_name("general_sequences.yaml")


def load_sequences() -> list[dict]:
    return [
        json.loads(line.strip()[2:])
        for line in SEQUENCES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- {")
    ]
