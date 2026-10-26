"""WA-77 (Alan, 25 Oct): an entry counts once it is saved. End-to-end tests
that send entries and then read stock, the work log or the report tap ✅ Save
first, as the worker would: every draft of the company is confirmed."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


async def tap_save(db: Any, organization_id: Any, actor_user_id: Any = None) -> int:
    """Confirm every fact of the company whose latest review is a draft."""
    import uuid

    from mesiri.infrastructure.postgres.repositories.fact_reviews import (
        PostgresFactReviewRepository,
    )

    organization_id = uuid.UUID(str(organization_id))
    actor_user_id = uuid.UUID(str(actor_user_id)) if actor_user_id else None

    async with db.transaction() as conn:
        drafts = (
            await conn.execute(
                text(
                    "SELECT fact_type, fact_id FROM ("
                    " SELECT DISTINCT ON (fact_type, fact_id) fact_type, fact_id, state"
                    " FROM fact_reviews WHERE organization_id = :org"
                    " ORDER BY fact_type, fact_id, created_at DESC) latest"
                    " WHERE state = 'draft'"
                ),
                {"org": organization_id},
            )
        ).all()
        reviews = PostgresFactReviewRepository(conn)
        for fact_type, fact_id in drafts:
            await reviews.confirm(
                organization_id=organization_id,
                fact_type=fact_type,
                fact_id=fact_id,
                actor_user_id=actor_user_id,
            )
    return len(drafts)
