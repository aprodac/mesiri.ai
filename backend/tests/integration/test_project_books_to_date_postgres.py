"""Project P&L's "to date" columns read the books from their first day, however long ago (found 21 Nov playing the
guided project: the page asked from 2000-01-01, the three-year limit refused it with a 422, and the columns quietly fell
back to this year's billing). Rolled back after the test."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope, SiteAccessScope
from mesiri.domains.accounts import router as accounts
from mesiri.domains.billing import router as billing

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration
LONG_AGO = dt.date(2021, 6, 1)


async def test_to_date_reads_from_the_books_first_day(conn) -> None:  # noqa: F811
    made = await create_company(
        conn, NewCompany(name="Old Builders", owner_name="Ravi Kumar", owner_phone="+919876500511",
                         project_name="Green Villa", site_names=("Main block",), auto_dpr=False), now=NOW)
    org, project = made.organization_id, made.project_id
    owner = AuthorizationContext(user_id=made.owner_user_id, organization_id=org, role="ADMIN", status="active",
                                 access_policy={},  # type: ignore[arg-type]
                                 project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                 site_scopes={project: SiteAccessScope(mode="all_sites", site_ids=set())})
    bank = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, opening_balance_date, "
        "created_by) VALUES (:id, :o, 'bank', 'Current account', 0, :d, :u)"),
        {"id": bank, "o": org, "d": LONG_AGO, "u": made.owner_user_id})
    await billing.put_contract(project, billing.ContractIn(new_client=billing.ClientIn(name="Mr Thomas")),
                               auth=owner, conn=conn)
    await billing.record_client_receipt(billing.ReceiptIn(
        project_id=project, kind="on_account", amount=Decimal(100000), account_id=bank, received_on=LONG_AGO),
        auth=owner, conn=conn)

    with pytest.raises(HTTPException) as e:  # the old way: refused
        await accounts.projects(date_from=dt.date(2000, 1, 1), date_to=None, since_start=False, auth=owner, conn=conn)
    assert e.value.status_code == 422

    out = await accounts.projects(date_from=None, date_to=None, since_start=True, auth=owner, conn=conn)
    assert out["date_from"] == LONG_AGO.isoformat()
