"""INF-07 / INF-08: errors reach the team without customer data, and /health
says whether the worker is alive.

The worker runs every WhatsApp message, so the uptime monitor must see it die
even while the web process still answers. Error reports go to a third party,
so the numbers in log lines must not.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from runtime import error_reporting
from runtime.error_reporting import _before_breadcrumb, _before_send, init_error_reporting
from runtime.lifecycle import worker_status


def _run(coro):
    return asyncio.run(coro)


class _Redis:
    def __init__(self, value=None, error=None, delay=0.0):
        self._value, self._error, self._delay = value, error, delay

    async def get_raw(self, _key):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._value


def _container(redis, queue=True):
    return SimpleNamespace(message_enqueuer=object() if queue else None, redis_client=redis)


# --- worker status -----------------------------------------------------------


def test_worker_alive_when_its_health_key_is_present():
    assert _run(worker_status(_container(_Redis("j_complete=1")))) == "alive"


def test_worker_down_when_the_key_has_expired():
    assert _run(worker_status(_container(_Redis(None)))) == "down"


def test_worker_off_without_a_queue_or_container():
    assert _run(worker_status(_container(_Redis("x"), queue=False))) == "off"
    assert _run(worker_status(None)) == "off"


def test_redis_failure_reads_as_down_and_never_raises():
    assert _run(worker_status(_container(_Redis(error=ConnectionError("no redis"))))) == "down"


def test_a_hung_redis_cannot_hang_the_health_probe(monkeypatch):
    real_wait_for = asyncio.wait_for

    async def fast_wait_for(aw, _timeout):
        return await real_wait_for(aw, 0.01)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)
    assert _run(worker_status(_container(_Redis("x", delay=1.0)))) == "down"


# --- error reporting ---------------------------------------------------------


def test_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_error_reporting("app") is False


def test_a_bad_dsn_never_stops_the_process_starting(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "not a dsn")
    assert init_error_reporting("worker") is False


def test_phone_numbers_are_masked_in_every_form():
    event = {
        "message": "reply failed for 919876543210",
        "logentry": {"message": "sender +91 98765 43210", "params": ["98765-43210"]},
        "exception": {"values": [{"value": "no user 917034926395"}]},
        "breadcrumbs": {"values": [{"message": "inbound from 919876543210"}]},
    }
    out = _before_send(event, {})
    text = repr(out)
    assert "9876543210" not in text and "98765 43210" not in text
    assert "7034926395" not in text
    assert text.count(error_reporting._MASK) == 5


def test_ids_counts_and_dates_are_left_alone():
    event = {"message": "job 12345 failed after 3 tries on 2026-10-23, order 98765"}
    assert _before_send(dict(event), {}) == event


def test_breadcrumbs_are_scrubbed_too():
    crumb = {"message": "send to 919876543210", "data": {"to": "919876543210"}}
    out = _before_breadcrumb(crumb, {})
    assert "919876543210" not in repr(out)
