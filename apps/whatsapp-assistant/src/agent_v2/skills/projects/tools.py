"""The projects skill's tools (request 197): a new project, a new site under a project.

Today's tools under their own names and specs (one place owns each tool's arguments:
runtime/agent/tools.py). They reach the existing ``project_create`` / ``site_create`` workflows
through the same query entry as the classic agent: the role check (ADMIN / PROJECT_MANAGER) and
the sender's organisation are enforced there, in code, never by the model. The user's Yes
confirms; nothing is made before it.
"""

from __future__ import annotations

from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.CREATE_PROJECT, classic.CREATE_SITE})
READ_TOOLS: frozenset[str] = frozenset()
