"""Drains DPR versions with a payload but no rendered PDF yet, renders one,
and stores it (#16 Daily Report Generation).

Invocable manually or via a cron entry -- not a persistent worker, same
convention as send_pending_notifications.py (which drains #9 Notifications'
queue). This is deliberately a SEPARATE script from backend's
run_dpr_generation.py: that script assembles the payload and writes
daily_report_versions rows; this one owns Playwright rendering (ADR-D8,
docs/execution/DAILY_REPORTING_PLAN.md -- reuses channel/receipt/'s
pattern), which has no reason to live in the backend process.

Object storage and the `PostgresDprRepository.set_rendered_object_key`
write happen from here too, the same cross-package-repository-call pattern
runtime/notification_query.py uses for `mark_sent`/`mark_skipped`: the
backend owns the SQL (one designated repository class), this script and the
backend script both call into it rather than each owning half the table.

Recommended VPS crontab entry (ops-managed, not tracked in this repo):
    5,20,35,50 * * * * cd /opt/mesiri/apps/whatsapp-assistant/src && \\
        PYTHONPATH=/opt/mesiri/shared/contracts/src:/opt/mesiri/platform/ai/src:/opt/mesiri/backend/src:/opt/mesiri/apps/whatsapp-assistant/src \\
        /opt/mesiri/.venv/bin/python -m runtime.render_pending_dpr_pdfs \\
        >> /var/log/mesiri/dpr-render.log 2>&1

Run:  python -m runtime.render_pending_dpr_pdfs
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any


async def render_and_store_version(
    *,
    renderer: Any,
    object_storage: Any,
    daily_report_id: Any,
    version_id: Any,
    code: str | None,
    payload: dict[str, Any] | str,
    letterhead: Any = None,
) -> str:
    """Render one DPR version to PDF and store it; returns the object key.
    The caller records the key on the version (`set_rendered_object_key`).
    Shared with runtime/project_auto_dpr.py, which renders right before
    sending so the owner gets the PDF itself (BE-16). ``letterhead`` (BE-19,
    channel/dpr_document/letterhead.py) adds the company's branding; without
    it the plain header is used."""
    import json

    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.template import render_html

    if isinstance(payload, str):
        payload = json.loads(payload)
    html = render_html(build_document_data(code=code or "DPR", payload=payload), letterhead)
    pdf_bytes = await renderer.render_pdf(html)
    object_key = f"dpr/{daily_report_id}/{version_id}.pdf"
    await object_storage.put_object(object_key, pdf_bytes, content_type="application/pdf")
    return object_key


async def run() -> dict[str, int]:
    from channel.dpr_document.letterhead import load_letterhead
    from channel.dpr_document.render import DprPdfRenderer
    from mesiri.bootstrap.settings import Settings as BackendSettings
    from mesiri.infrastructure.objectstorage import build_object_storage
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

    backend_settings = BackendSettings()
    db = PostgresDatabase(backend_settings.postgres)
    await db.connect()
    object_storage = build_object_storage(backend_settings)
    renderer = DprPdfRenderer()

    counts = {"rendered": 0, "failed": 0}
    try:
        async with db.transaction() as conn:
            repo = PostgresDprRepository(conn)
            pending = await repo.list_unrendered_versions()

        for row in pending:
            try:
                async with db.transaction() as conn:
                    letterhead = await load_letterhead(conn, object_storage, row["daily_report_id"])
                object_key = await render_and_store_version(
                    renderer=renderer,
                    object_storage=object_storage,
                    daily_report_id=row["daily_report_id"],
                    version_id=row["version_id"],
                    code=row["code"],
                    payload=row["payload"],
                    letterhead=letterhead,
                )

                async with db.transaction() as conn:
                    repo = PostgresDprRepository(conn)
                    await repo.set_rendered_object_key(
                        version_id=row["version_id"], object_key=object_key
                    )
                counts["rendered"] += 1
            except Exception:  # noqa: BLE001 -- one bad version must not stop the drain
                counts["failed"] += 1
    finally:
        await renderer.close()
        await db.disconnect()

    return counts


def main() -> int:
    counts = asyncio.run(run())
    print(f"dpr-render: rendered {counts['rendered']}, failed {counts['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
