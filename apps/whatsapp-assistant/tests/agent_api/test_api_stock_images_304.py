"""[304] (15 Nov, Aprodac: "ethra stock baaki undu, full ellathilum" came back as a long text list over two projects
and four sites): stock of more than one material is drawn by the code as pictures, from the same route the dashboard
reads, as many as the list needs ("1/2", "2/2"); a site is never cut in two when it fits whole on the next one.
[302]: minus stock is never "stock left": it is marked CHECK, and the model is told to name it.

Guards: an empty list sends nothing and says so; a list too long for six pictures asks which project or site; a
failed picture is never called sent; the reply never repeats the list.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from agent_api import stock_images as si

DAY = dt.date(2026, 11, 15)
CTX = SimpleNamespace(
    projects=[SimpleNamespace(id="p1", name="Green Villa"), SimpleNamespace(id="p2", name="Lake View")],
    sites=[SimpleNamespace(id="s1", name="Annex"), SimpleNamespace(id="s2", name="Main block"),
           SimpleNamespace(id="s3", name="Tower A")])


def _row(project: str, site: str, name: str, left: float, unit: str = "bags", **more: Any) -> dict:
    return {"project_id": project, "site_id": site, "material_name": name, "current_stock": Decimal(str(left)),
            "unit": unit, **more}


ROWS = [_row("p1", "s1", "Steel", 2560, "kg"), _row("p1", "s1", "Cement", 36, below_min=True),
        _row("p1", "s2", "Cement", 2.2), _row("p2", "s3", "Binding Wire", -30, "kg"),
        _row("p2", "s3", "Cement", 140, on_order=Decimal(200)), _row("p2", "s3", "M Sand", 0, "cum")]


class _Client:
    def __init__(self, rows: Any, ok: bool = True) -> None:
        self.rows, self.ok, self.asked = rows, ok, []

    async def call(self, method: str, path: str, params: Any = None, **kw: Any) -> Any:  # noqa: ANN401
        self.asked.append((method, path, params))
        return SimpleNamespace(ok=self.ok, body=self.rows)


class _Out:
    def __init__(self, fail_at: int = 0) -> None:
        self.images: list[tuple[bytes, str]] = []
        self.fail_at = fail_at

    async def render(self, html: str) -> bytes:
        return html.encode()

    async def send(self, wa_id: str, image: bytes, *, filename: str, shows: str) -> bool:
        if self.fail_at and len(self.images) + 1 == self.fail_at:
            return False
        self.images.append((image, filename))
        return True


async def _send(rows: Any, out: _Out, arguments: dict | None = None) -> tuple[dict, _Client]:
    client = _Client(rows)
    result = await si.send(client, out.render, out.send, "91", CTX, DAY, arguments or {})  # type: ignore[arg-type]
    return result, client


# -- the reported message -------------------------------------------------------------------------------------------

async def test_overall_stock_goes_as_a_picture_grouped_by_project_and_site() -> None:
    out = _Out()
    result, client = await _send(ROWS, out)
    assert client.asked == [("GET", "/materials/inventory", {})]
    assert result["status"] == "sent 1 picture of 1 to their WhatsApp" and "Never repeat the list" in result["note"]
    page = out.images[0][0].decode()
    for words in ("Green Villa", "Lake View", "Annex", "Main block", "Tower A", "2,560", "2.2", "140"):
        assert words in page
    assert page.index("Green Villa") < page.index("Annex") < page.index("Main block") < page.index("Lake View")


async def test_minus_stock_is_marked_check_and_named_to_the_model() -> None:
    out = _Out()
    result, _ = await _send(ROWS, out)
    page = out.images[0][0].decode()
    assert "CHECK" in page and "30 kg more used than received" in page
    assert "Binding Wire" in result["check"]
    assert "LOW" in page and "OUT" in page and "200 bags on order" in page


async def test_a_long_list_goes_on_in_more_pictures_numbered() -> None:
    rows = [_row("p1", "s1", f"Item {i:02}", i + 1) for i in range(40)]
    out = _Out()
    result, _ = await _send(rows, out)
    assert len(out.images) == 2 and result["status"] == "sent 2 pictures of 2 to their WhatsApp"
    first, second = (img.decode() for img, _ in out.images)
    assert ">1/2<" in first and ">2/2<" in second and "Annex (continued)" in second
    assert all(f"Item {i:02}" in first + second for i in range(40))


def test_a_site_that_fits_on_the_next_picture_is_never_cut() -> None:
    big = si.Site("Green Villa", "Annex", [si.Line(f"M{i}", "1", "nos", "ok") for i in range(15)])
    small = si.Site("Green Villa", "Main block", [si.Line(f"N{i}", "1", "nos", "ok") for i in range(10)])
    pages = si.paginate([big, small])
    assert [[(s.name, len(s.lines)) for s in p] for p in pages] == [[("Annex", 15)], [("Main block", 10)]]


async def test_narrowed_to_a_site_names_it_and_passes_the_filter() -> None:
    out = _Out()
    _, client = await _send(ROWS[:2], out, {"site_id": "s1"})
    assert client.asked[0][2] == {"site_id": "s1"} and "Annex · 15 Nov 2026" in out.images[0][0].decode()


# -- guards ---------------------------------------------------------------------------------------------------------

async def test_guard_no_stock_sends_nothing_and_says_so() -> None:
    out = _Out()
    result, _ = await _send([], out)
    assert out.images == [] and result["status"].startswith("nothing sent")


async def test_guard_too_long_for_six_pictures_asks_which_project_or_site() -> None:
    rows = [_row("p1", "s1", f"Item {i:03}", 1) for i in range(200)]
    out = _Out()
    result, _ = await _send(rows, out)
    assert out.images == [] and "Ask which project or site" in result["status"]


async def test_guard_a_failed_picture_is_never_called_sent() -> None:
    rows = [_row("p1", "s1", f"Item {i:02}", 1) for i in range(40)]
    out = _Out(fail_at=2)
    result, _ = await _send(rows, out)
    assert len(out.images) == 1 and "sent 1 picture of 2" in result["status"] and "Only 1 of 2" in result["note"]
    nothing = _Out(fail_at=1)
    result, _ = await _send(ROWS, nothing)
    assert result["status"].startswith("not sent")


def test_guard_no_check_note_when_nothing_is_below_zero() -> None:
    page = si.page_html(si.paginate(si.sites_of(ROWS[:2], {"p1": "Green Villa"}, {"s1": "Annex"}))[0],
                        number=1, total=1, day=DAY, where="All your sites")
    assert "CHECK" not in page and ">1/1<" not in page


def test_the_sop_sends_stock_of_several_materials_as_pictures() -> None:
    from agent_api.agent import SOP

    assert "`send_stock_list`" in SOP and "NEGATIVE_STOCK" in SOP
