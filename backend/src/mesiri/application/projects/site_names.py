"""QA-04 step 2.1: a project's sites have different names.

"villa 1" was saved beside "Villa 1" (20 Nov, production): both routers that add or rename a site only checked that the
name was not empty. On WhatsApp "villa 1" then matched two sites. Projects already refuse a name the company has
([207]); this is the same rule for the sites of one project, in one place for both routers (the backend's and the
assistant's, which production serves).

Names compare as projects do: case, spaces and character width do not count. Archived sites count too, so an
archived "Villa 1" is renamed or brought back, never doubled. Another project may have its own "Villa 1".
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import Any

import sqlalchemy as sa


def same_site_name(name: str | None) -> str:
    """A site name as compared for duplicates: "Villa 1", "villa  1" and "VILLA 1" are one site."""
    return " ".join(unicodedata.normalize("NFKC", str(name or "")).casefold().split())


async def existing_site_named(conn: Any, organization_id: Any, project_id: uuid.UUID, name: str, *,
                              other_than: uuid.UUID | None = None) -> str | None:
    """The name of this project's site with the same name, else None."""
    wanted = same_site_name(name)
    if not wanted:
        return None
    rows = await conn.execute(sa.text(
        "SELECT id, name FROM sites WHERE organization_id = :org AND project_id = :p",
    ).bindparams(org=organization_id, p=project_id))
    for row in rows.fetchall():
        if row.id != other_than and same_site_name(row.name) == wanted:
            return row.name
    return None


def already_a_site(project_site: str) -> str:
    """The one wording for the refusal, on add and on rename."""
    return f"{project_site} is already a site of this project"

