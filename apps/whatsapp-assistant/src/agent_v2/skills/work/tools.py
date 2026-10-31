"""The work skill's tools (request 185): work done: progress, completed work, quantities, corrections of a logged figure.

Today's tools, under their own names and specs (one place owns each tool's arguments:
runtime/agent/tools.py). A write tool only puts a line below the reply; the Save tap writes.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.SAVE_WORK_DONE, classic.CORRECT_WORK_QUANTITY})
READ_TOOLS = frozenset({classic.QUERY_WORK_LOG})
