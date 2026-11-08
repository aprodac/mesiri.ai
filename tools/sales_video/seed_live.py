"""Demo data for Live plans on a local Mesiri (never production): a project with the architect's floor plans and a
structural set, both tracked, work across trades the way site sends it, and photos on some of it.

    python tools/sales_video/seed_live.py OUT_DIR STRUCTURE.pdf

The photos are drawn here (brick, plaster, tiles, footing steel): stand-ins for site photos, not real ones. Needs the
local API on :8000 with local object storage (MESIRI_OBJECT_STORAGE__LOCAL_ROOT), and its database.
"""

from __future__ import annotations

import io
import json
import os
import random
import sys
import uuid
from pathlib import Path

import httpx
import sqlalchemy as sa

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floor_plans_pdf import build as floor_plans  # noqa: E402


def photo(kind: str, seed: int) -> bytes:
    """A stand-in site photo: brick, plaster, tiles or footing steel, with light and noise."""
    from PIL import Image, ImageDraw, ImageFilter

    rnd = random.Random(seed)
    w, h = 640, 480
    img = Image.new("RGB", (w, h), (120, 110, 100))
    d = ImageDraw.Draw(img)
    if kind == "brick":
        for row in range(0, h, 34):
            off = 0 if (row // 34) % 2 else 40
            for col in range(-80, w, 82):
                c = rnd.randint(140, 175)
                d.rectangle([col + off, row, col + off + 76, row + 28], fill=(c, c // 2 + rnd.randint(0, 15), c // 3))
    elif kind == "plaster":
        img = Image.new("RGB", (w, h), (200, 196, 186))
        d = ImageDraw.Draw(img)
        for _ in range(4000):
            x, y, g = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(175, 215)
            d.point((x, y), fill=(g, g - 4, g - 12))
    elif kind == "tiles":
        for row in range(0, h, 80):
            for col in range(0, w, 80):
                g = rnd.randint(215, 235)
                d.rectangle([col + 2, row + 2, col + 78, row + 78], fill=(g, g, g - 6))
        d.polygon([(0, h), (w, h), (w, int(h * 0.7))], fill=(90, 80, 70))
    else:  # footing steel and concrete
        img = Image.new("RGB", (w, h), (150, 150, 145))
        d = ImageDraw.Draw(img)
        for k in range(14):
            y = 40 + k * 30
            d.line([(30, y), (w - 30, y)], fill=(95, 60, 40), width=5)
        for k in range(14):
            x = 50 + k * 40
            d.line([(x, 30), (x, h - 30)], fill=(105, 65, 45), width=5)
    # daylight from the top left, and a little blur like a phone camera
    shade = Image.linear_gradient("L").resize((w, h)).point(lambda v: 255 - v // 3)
    img = Image.composite(img, Image.new("RGB", (w, h), (40, 40, 40)), shade).filter(ImageFilter.GaussianBlur(0.8))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=82)
    return out.getvalue()


def main() -> int:
    out, structure = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    root = Path(os.environ["MESIRI_OBJECT_STORAGE__LOCAL_ROOT"])
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
        c.execute(sa.text("INSERT INTO projects (id, organization_id, name, created_at, updated_at) VALUES "
                          "(:id, :org, 'Commercial building, Kondotty', now(), now())"), {"id": project, "org": org})
        c.execute(sa.text("INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                          "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())"),
                  {"id": site, "p": project, "org": org})
    token = create_access_token(data={"sub": str(user), "org": str(org), "role": "admin"})
    api = httpx.Client(base_url="http://localhost:8000", headers={"Authorization": f"Bearer {token}"}, timeout=90,
                       trust_env=False)
    for name, data in (("A-101 Floor plans.pdf", floor_plans()), ("Structure detail.pdf", structure.read_bytes())):
        r = api.post(f"/projects/{project}/documents", files={"file": (name, data, "application/pdf")})
        r.raise_for_status()
        api.post(f"/documents/{r.json()['id']}/track").raise_for_status()

    photos: list[tuple[str, str]] = []

    def work(place: str, kind: str, finished: bool, day: int, pic: str | None = None) -> None:
        r = api.post("/progress/activities", json={
            "project_id": str(project), "site_id": str(site), "activity_date": f"2026-11-{day:02d}", "work_type": kind,
            "narrative": f"{place} {kind}", "place": place, "finished": finished, "quantities": [],
            "source": "whatsapp_text"})
        r.raise_for_status()
        if pic:
            photos.append((r.json()["id"], pic))

    for g in ("A3", "A5", "A7", "B3", "B5", "B7", "D3", "D5", "D7", "A1", "D1", "E1", "B2"):
        work(f"{g} footing concreted", "Footing concrete", True, 1, "steel" if g in ("B3", "D5", "B2") else None)
    for g in ("E3", "E5", "E7", "A9"):
        work(f"{g} footing steel tied", "Footing concrete", False, 2, "steel" if g == "E5" else None)
    for room in ("shop-1", "shop-2", "shop-3", "lobby", "stair", "toilet", "store"):
        work(f"ground floor {room} brickwork", "Brickwork", True, 3, "brick" if room in ("shop-1", "store") else None)
    for room in ("shop-1", "shop-2", "lobby", "toilet"):
        work(f"ground floor {room} plastering", "Plastering", True, 5, "plaster" if room == "shop-1" else None)
    work("ground floor shop-3 plastering", "Plastering", False, 6)
    work("ground floor toilet tiling", "Tiling", True, 7, "tiles")
    work("ground floor shop-1 tiling", "Tiling", False, 8, "tiles")
    for room in ("office-1", "office-2", "conference", "reception", "stair"):
        work(f"first floor {room} brickwork", "Brickwork", room != "conference", 6, "brick" if room == "office-1" else None)
    work("first floor pantry brickwork", "Brickwork", False, 8)

    with engine.begin() as c:
        for k, (activity, kind) in enumerate(photos):
            key = f"media/demo/{activity}/{k}.jpg"
            path = root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(photo(kind, k))
            c.execute(sa.text("INSERT INTO progress_attachments (id, parent_type, parent_id, media_object_key, "
                              "attachment_type, mime_type, uploaded_by_user_id) VALUES (:id, 'ACTIVITY', :a, :key, "
                              "'photo', 'image/jpeg', :u)"),
                      {"id": uuid.uuid4(), "a": activity, "key": key, "u": user})
    (out / "live.json").write_text(json.dumps({"token": token, "project": str(project), "site": str(site)}))
    print("live demo ready:", project, f"{len(photos)} photos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
