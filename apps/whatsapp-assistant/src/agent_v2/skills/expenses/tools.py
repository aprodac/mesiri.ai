"""The expenses skill's tools (request 185): money spent on site: expenses, bills, balances.

Today's tools, under their own names and specs (one place owns each tool's arguments:
runtime/agent/tools.py). A write tool only puts a line below the reply; the Save tap writes.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.SAVE_EXPENSE, classic.TRANSFER_MONEY})
READ_TOOLS = frozenset({classic.QUERY_EXPENSES})
