"""The issues skill's tools (request 185): problems on site: delays, breakdowns, rain, shortages, safety, quality; closing them.

Today's tools, under their own names and specs (one place owns each tool's arguments:
runtime/agent/tools.py). A write tool only puts a line below the reply; the Save tap writes.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.REPORT_ISSUE, classic.UPDATE_ISSUE})
READ_TOOLS = frozenset({classic.QUERY_OPEN_NEEDS})
