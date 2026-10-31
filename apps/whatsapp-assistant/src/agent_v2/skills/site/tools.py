"""The site skill's tools (request 185): the site's day: weather, whether it worked, tomorrow's plan, where they work today, questions for the engineer.

Today's tools, under their own names and specs (one place owns each tool's arguments:
runtime/agent/tools.py). A write tool only puts a line below the reply; the Save tap writes.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.SET_SITE_CONDITIONS, classic.NOTE_FOR_ENGINEER, classic.SET_WORK_SITE})
READ_TOOLS = frozenset({classic.MY_SCOPE})
