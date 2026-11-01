"""The general skill's tools (request 194): taking back or correcting something already SAVED,
whatever its module. Today's tools under their own names and specs (runtime/agent/tools.py):
a removal is confirmed with a Yes card first; a change of a saved entry is a Change line saved by
tap. Nothing is removed or changed before the tap.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.CHANGE_OR_UNDO, classic.UNDO_LAST})
READ_TOOLS: frozenset[str] = frozenset()
