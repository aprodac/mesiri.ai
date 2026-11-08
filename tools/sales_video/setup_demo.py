"""Demo data for the sales video's screen recordings (a local Mesiri, never production).

    python tools/sales_video/setup_demo.py OUT_DIR

Needs the local API on http://localhost:8000 (with its database). Makes a fresh demo company "Thanal Constructions"
with an admin (Ravi Kumar), the project "Commercial building, Kondotty" and its site; floors x rooms with some work
already reported; a building permit, an agreement and S-101 rev B in Documents; and writes OUT_DIR/demo.json (token,
ids) and the files the recording uploads (S-101 rev C).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import httpx
import sqlalchemy as sa

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token


def drawing(rev: str, note: str) -> bytes:
    """A small column layout sheet, numbered S-101, at a revision."""
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=8)
    for x, y, t in [(120, 120, "C1"), (300, 120, "C2"), (480, 120, "C1"), (120, 320, "C3"), (300, 320, "C3"),
                    (480, 320, "C2"), (100, 500, note), (300, 722, "DWG NO"), (300, 734, "S-101"), (250, 722, "REV"),
                    (250, 734, rev), (409, 722, "DWG.TITLE:"), (469, 734, "COLUMN LAYOUT"), (458, 771, "1:100")]:
        pdf.text(x, y, t)
    return bytes(pdf.output())


def paper(title: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.text(20, 30, title)
    pdf.set_font("Helvetica", size=10)
    pdf.text(20, 45, "Commercial building, Kondotty. Demo document for the sales video.")
    return bytes(pdf.output())


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(Settings().postgres.dsn().replace("+asyncpg", ""))
    org, user, project, site = (uuid.uuid4() for _ in range(4))
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                          "updated_at) VALUES (:id, 'Thanal Constructions', 'local', 'default', 'active', now(), now())"),
                  {"id": org})
        c.execute(sa.text("INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                          "access_policy, created_at, updated_at) VALUES (:id, :org, :email, 'x', 'Ravi Kumar', 'admin', "
                          "'active', CAST('{\"mode\": \"all_projects\", \"projects\": []}' AS jsonb), now(), now())"),
                  {"id": user, "org": org, "email": f"ravi.{uuid.uuid4().hex[:6]}@demo.mesiri"})
        c.execute(sa.text("INSERT INTO projects (id, organization_id, name, client, created_at, updated_at) VALUES "
                          "(:id, :org, 'Commercial building, Kondotty', 'Mr. Abdullakutty', now(), now())"),
                  {"id": project, "org": org})
        c.execute(sa.text("INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                          "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())"),
                  {"id": site, "p": project, "org": org})
    token = create_access_token(data={"sub": str(user), "org": str(org), "role": "admin"})
    api = httpx.Client(base_url="http://localhost:8000", headers={"Authorization": f"Bearer {token}"}, timeout=60,
                       trust_env=False)

    def up(name: str, data: bytes, **form: str) -> None:
        r = api.post(f"/projects/{project}/documents", files={"file": (name, data, "application/pdf")}, data=form)
        r.raise_for_status()

    up("S-101 Column layout rev B.pdf", drawing("B", "first issue"))
    up("Building permit 2026.pdf", paper("Building permit"), valid_until="2026-12-03")
    up("Construction agreement signed.pdf", paper("Construction agreement"))
    (out / "S-101 Column layout rev C.pdf").write_bytes(drawing("C", "C2 moved 30 cm east"))

    api.post(f"/projects/{project}/places/setup", json={
        "floors": ["Ground Floor", "First Floor"], "rooms": ["Room 1", "Room 2", "Room 3", "Kitchen", "Toilet"]
    }).raise_for_status()

    def work(place: str, kind: str, finished: bool, day: int) -> None:
        api.post("/progress/activities", json={
            "project_id": str(project), "site_id": str(site), "activity_date": f"2026-11-{day:02d}",
            "work_type": kind, "narrative": f"{place} {kind}", "place": place, "finished": finished,
            "quantities": []}).raise_for_status()

    for room in ("Room 1", "Room 2", "Room 3", "Kitchen", "Toilet"):
        work(f"ground floor {room}", "Brickwork", True, 2)
        work(f"ground floor {room}", "Plastering", room != "Toilet", 4)
    work("ground floor toilet", "Tiling", False, 6)
    for room, done in (("Room 1", True), ("Room 2", True), ("Room 3", True), ("Kitchen", False)):
        work(f"first floor {room}", "Brickwork", done, 5)
    work("first floor room 1", "Plastering", True, 7)
    work("first floor room 3", "Plastering", False, 7)

    (out / "demo.json").write_text(json.dumps({"token": token, "project": str(project), "site": str(site),
                                               "org": str(org)}, indent=1))
    print("demo ready:", project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
