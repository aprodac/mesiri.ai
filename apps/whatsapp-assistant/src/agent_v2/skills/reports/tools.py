"""The reports skill's tools (request 185): the daily progress report (DPR) and project status.

Today's tools, under their own names and specs (one place owns each tool's arguments:
runtime/agent/tools.py). A write tool only puts a line below the reply; the Save tap writes.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.REQUEST_DPR})
READ_TOOLS = frozenset({classic.QUERY_PROJECT})
