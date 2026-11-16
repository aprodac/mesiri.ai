"""Shared set-up for the contract tests (they need a live Postgres; marked ``integration``).

INF-33: every contract file starts on a database with no company data in it, whatever file ran before. Each file's
own clean-up only knew the tables it fills, so a file broke when it ran after another that filled a table its list
did not know (``vendors`` still referenced by ``work_orders``), and most files could not run together. Before a
file's first database test, ``tenant_data.wipe`` removes every company's rows, read from the schema itself, and
leaves the reference data the migrations seed. A new table is covered the day its migration lands.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

_started: set[str] = set()


def _wipe_now() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from contract.tenant_data import wipe
    from mesiri.bootstrap.settings import Settings

    async def run() -> None:
        engine = create_async_engine(Settings().postgres.dsn(), echo=False)
        try:
            await wipe(engine)
        finally:
            await engine.dispose()

    # In a thread of its own: the test's event loop (pytest-asyncio) must not be touched.
    failure: list[BaseException] = []

    def target() -> None:
        try:
            asyncio.run(run())
        except BaseException as exc:  # noqa: BLE001 -- handed back to the test below
            failure.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]


@pytest.fixture(autouse=True)
def _start_each_file_without_company_data(request: pytest.FixtureRequest):
    """Before the first database test of each contract file: no company data left by another file."""
    if request.node.get_closest_marker("integration") is not None:
        path = str(request.node.path)
        if path not in _started:
            _started.add(path)
            _wipe_now()
    yield
