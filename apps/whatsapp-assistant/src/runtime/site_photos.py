"""A "Site Update" photo batch, attached to the work it shows (PHO-01).

The tap on "Site Update" used to look for an open activity with no site at
all, which never found one ("there's no activity in progress right now",
straight after the work was reported), and dropped the caption. Here the
activity is looked up at today's site (else the sender's sites) and each
photo keeps the words it was sent with.
"""

from __future__ import annotations

from typing import Any

from channel.replies import (
    render_evidence_attached_reply,
    render_no_open_activity_for_evidence_reply,
)


async def attach_site_update_photos(
    held_batch: list[Any],
    *,
    ctx: Any,
    work_site: Any | None,
    activity_query: Any,
    evidence_query: Any,
    correlation_id: str,
) -> str:
    """Attach every photo of the batch to the sender's activity; the reply to send."""
    today_site = await work_site.today(ctx) if work_site is not None else None
    own_sites = [str(s.id) for s in getattr(ctx, "sites", None) or []]
    sites = [str(today_site[1])] if today_site else own_sites
    found = await activity_query.find_activity_for_photos(
        organization_id=ctx.organization_id, reported_by_user_id=ctx.user_id, site_ids=sites
    )
    if found is None and today_site and own_sites:
        # Reported at another of their sites: the photos still belong to that work.
        found = await activity_query.find_activity_for_photos(
            organization_id=ctx.organization_id, reported_by_user_id=ctx.user_id, site_ids=own_sites
        )
    if found is None:
        return render_no_open_activity_for_evidence_reply()
    pairs = [(m.media.object_key, getattr(m, "text", None)) for m in held_batch if m.media is not None]
    created = await evidence_query.attach_photos(
        organization_id=ctx.organization_id,
        activity_id=found["activity_id"],
        media_object_keys=[key for key, _ in pairs],
        captions=[text for _, text in pairs],
        uploaded_by=ctx.user_id,
        correlation_id=correlation_id,
    )
    bits = [b for b in (found.get("work_type"), found.get("narrative")) if b]
    return render_evidence_attached_reply(count=len(created), activity_summary=" — ".join(bits) if bits else None)
