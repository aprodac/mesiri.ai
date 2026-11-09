"""Tasks: a BOQ line can be deleted under a task that expects a quantity of it (TSK-03).

0533's ``ck_tasks_expected_quantity`` tied an expected quantity to a BOQ line. ``planned_item_id`` is ``ON DELETE SET
NULL``, so deleting a BOQ line under such a task left the quantity without its line and the check refused the delete
(found by the BOQ contract tests on 9 Nov 2026: every BOQ line delete failed once a task expected a quantity of it).
The check now only asks for a positive quantity; "a quantity needs a line" stays a rule of ``POST`` / ``PATCH
/tasks``, where a person is there to be told.

Relaxes a check, touches no row. Downgrade puts the old check back only when no row breaks it.

Revision ID: 0537
Revises: 0536
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0537"
down_revision = "0536"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_expected_quantity")
    op.execute("ALTER TABLE tasks ADD CONSTRAINT ck_tasks_expected_quantity "
               "CHECK (expected_quantity IS NULL OR expected_quantity > 0)")


def downgrade() -> None:
    op.execute("UPDATE tasks SET expected_quantity = NULL WHERE planned_item_id IS NULL AND expected_quantity IS NOT NULL")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_expected_quantity")
    op.execute("ALTER TABLE tasks ADD CONSTRAINT ck_tasks_expected_quantity CHECK (expected_quantity IS NULL "
               "OR (expected_quantity > 0 AND planned_item_id IS NOT NULL))")
