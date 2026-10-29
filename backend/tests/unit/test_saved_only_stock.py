"""WA-77 (Alan, 25 Oct) for stock: what is shown as stock (the dashboard,
WhatsApp answers, the DPR's opening/closing, the ledger) is what is saved; an
entry waiting for its Save on WhatsApp is left out. The over-stock hint while
capturing still counts it (it was reported)."""

from __future__ import annotations

import inspect
import uuid

from mesiri.application.dpr import fact_review
from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository


def test_the_movement_rule_covers_receipts_usage_and_transfer_halves():
    sql = fact_review.movement_counted_sql("mm")
    assert "mm.source_type = 'material_usage'" in sql
    assert "mm.source_type = 'material_receipt'" in sql
    # The incoming half of a transfer follows its reviewed outgoing half.
    assert "u_c.transfer_id = r_c.transfer_id" in sql and "fr_c.fact_id = u_c.id" in sql


class _Result:
    def mappings(self):
        return self

    def all(self):
        return []


class _Conn:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, stmt, *args, **kwargs):
        self.sql.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return _Result()


async def test_stock_levels_leave_out_unsaved_entries_unless_asked():
    conn = _Conn()
    repo = PostgresMaterialReadRepository(conn)
    await repo.get_stock_levels(uuid.uuid4())
    await repo.get_stock_levels(uuid.uuid4(), include_unsaved=True)

    shown, hint = conn.sql
    assert "fact_reviews" in shown and "material_movements.source_type" in shown
    assert "fact_reviews" not in hint


def test_the_ledger_and_the_dpr_stock_follow_the_rule():
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

    assert "movement_counted_sql" in inspect.getsource(PostgresMaterialReadRepository.get_ledger)
    assert 'movement_counted_sql("mm")' in inspect.getsource(PostgresDprRepository.assemble_site_day_with_drafts)
