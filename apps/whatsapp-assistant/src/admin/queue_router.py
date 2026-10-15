"""Durable ingress queue visibility for the control panel (platform-admin only).

Exists so "is the ARQ worker actually consuming the Redis queue" is
answerable from the dashboard. Before this, the only
way to check was SSH + `journalctl -u mesiri-worker` + `redis-cli`, which is
exactly the gap that let the worker sit un-deployed and silently swallow
messages after the ARQ rollout (see infra/mesiri-worker.service and
deploy.yml's "Worker health check" step, added for the same incident).

Read-only: reads ARQ's own health-check key (see runtime/queue.py), which
the worker writes to itself every HEALTH_CHECK_INTERVAL_SECONDS and which
Redis expires automatically if the worker stops updating it -- so this
adds no polling loop and no new write path of its own.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from mesiri.domains.shared.auth import require_platform_admin
from runtime.queue import HEALTH_CHECK_INTERVAL_SECONDS, HEALTH_CHECK_KEY, parse_worker_health

router = APIRouter(prefix="/admin/queue", tags=["admin"])


class QueueHealthResponse(BaseModel):
    # False when this deployment isn't running against real Redis at all
    # (dev/test on FakeRedis) -- there is no queue to report on, not an
    # error state.
    queue_enabled: bool
    health_check_interval_seconds: int
    # True only when ARQ's own health-check key is present and fresh --
    # Redis expires it automatically if the worker stops ticking, so
    # "present" already means "was alive within the last interval".
    worker_alive: bool
    jobs_complete: int | None = None
    jobs_failed: int | None = None
    jobs_retried: int | None = None
    jobs_ongoing: int | None = None
    queue_depth: int | None = None
    raw_status: str | None = None


@router.get("/health", response_model=QueueHealthResponse)
async def get_queue_health(
    request: Request,
    _admin: dict = Depends(require_platform_admin),
) -> QueueHealthResponse:
    container = request.app.state.container
    queue_enabled = container.message_enqueuer is not None

    raw = await container.redis_client.get_raw(HEALTH_CHECK_KEY)
    if raw is None:
        return QueueHealthResponse(
            queue_enabled=queue_enabled,
            health_check_interval_seconds=HEALTH_CHECK_INTERVAL_SECONDS,
            worker_alive=False,
        )

    parsed = parse_worker_health(raw)
    if parsed is None:
        # Key exists (worker is alive and ticking) but the text didn't match
        # the expected ARQ format -- report alive with what we actually have
        # rather than hiding a live worker behind a parse failure.
        return QueueHealthResponse(
            queue_enabled=queue_enabled,
            health_check_interval_seconds=HEALTH_CHECK_INTERVAL_SECONDS,
            worker_alive=True,
            raw_status=raw,
        )

    return QueueHealthResponse(
        queue_enabled=queue_enabled,
        health_check_interval_seconds=HEALTH_CHECK_INTERVAL_SECONDS,
        worker_alive=True,
        jobs_complete=parsed.jobs_complete,
        jobs_failed=parsed.jobs_failed,
        jobs_retried=parsed.jobs_retried,
        jobs_ongoing=parsed.jobs_ongoing,
        queue_depth=parsed.queue_depth,
        raw_status=parsed.raw,
    )
