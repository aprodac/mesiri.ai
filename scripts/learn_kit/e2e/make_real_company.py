import asyncio
import datetime as dt
import json

import jwt
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY


async def main():
    e = create_async_engine("postgresql+asyncpg://mesiri:mesiri_local_dev@127.0.0.1:5432/mesiri")
    async with e.begin() as c:
        made = await create_company(c, NewCompany(name="Acme Real Builders", owner_name="Asha Menon", owner_email=f"asha{dt.datetime.now().timestamp()}@acme.test", project_name="Real Tower", site_names=("Block 1",)))
    tok = jwt.encode({"sub": str(made.owner_user_id), "org": str(made.organization_id), "role": "ADMIN", "exp": dt.datetime.now(dt.UTC)+dt.timedelta(hours=1)}, SECRET_KEY, algorithm=ALGORITHM)
    print(json.dumps({"token": tok, "org": str(made.organization_id), "project": str(made.project_id)}))
asyncio.run(main())
