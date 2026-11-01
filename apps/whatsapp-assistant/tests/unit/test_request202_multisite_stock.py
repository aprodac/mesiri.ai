"""Request 202: "how much cement is left?" for a sender with several sites reads every site."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.inventory_query import query_sites
from workflows.material_inventory_query.nodes import generate_inventory_reply


def _lvl(stock):
    return {"material_name": "Cement", "unit": "bags", "received": stock, "used": 0.0, "current_stock": stock}


class _Service:
    """Stock by site id; a site not in the table holds nothing."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    async def query(self, **kw):
        self.calls.append(kw)
        return [_lvl(self.table[kw["site_id"]])] if kw["site_id"] in self.table else []


SITES = [("p1", "gv", "Green Villa"), ("p1", "sb", "Site B"), ("p2", "lm", "Live Mart B")]


async def test_multi_site_read_sums_per_site_and_a_new_empty_project_hides_nothing():
    service = _Service({"gv": 117.0})
    total, by_site = await query_sites(service, organization_id="o", sites=SITES, material_name="cement")
    assert total[0]["current_stock"] == 117.0
    assert [r["site"] for r in by_site] == ["Green Villa", "Site B", "Live Mart B"]
    assert len(service.calls) == 3


async def test_stock_adds_up_across_sites():
    total, _ = await query_sites(_Service({"gv": 100.0, "sb": 17.0}), organization_id="o", sites=SITES, material_name=None)
    assert total[0]["current_stock"] == 117.0


async def test_a_failing_site_is_left_out_not_fatal():
    class Boom(_Service):
        async def query(self, **kw):
            if kw["site_id"] == "sb":
                raise RuntimeError("x")
            return await super().query(**kw)

    total, by_site = await query_sites(Boom({"gv": 5.0}), organization_id="o", sites=SITES, material_name=None)
    assert total[0]["current_stock"] == 5.0 and len(by_site) == 2


def test_reply_names_each_site_and_says_none():
    by_site = [{"site": "Green Villa", "levels": [_lvl(117.0)]}, {"site": "Site B", "levels": []}]
    out = generate_inventory_reply(
        {"collected_fields": {"material_name": "cement", "inventory_levels": [_lvl(117.0)], "inventory_by_site": by_site}}
    )["pending_prompt"]
    assert "Green Villa — 117 bags" in out and "Site B — none" in out and "Total: 117 bags" in out


def test_no_recorded_stock_only_when_no_site_has_any():
    out = generate_inventory_reply(
        {"collected_fields": {"material_name": "cement", "inventory_levels": [], "inventory_by_site": [{"site": "A", "levels": []}, {"site": "B", "levels": []}]}}
    )["pending_prompt"]
    assert "any recorded stock for cement" in out


def test_single_site_is_unchanged():
    out = generate_inventory_reply(
        {"collected_fields": {"material_name": "cement", "inventory_levels": [_lvl(30.0)]}}
    )["pending_prompt"]
    assert "In stock: 30 bags" in out


async def test_seed_reads_all_sites_only_when_given_them():
    from runtime.inbound_journey.seeding import _inject_inventory_context

    def event():
        return SimpleNamespace(
            event_type=__import__("mesiri_contracts.assistant.canonical_event", fromlist=["x"]).CanonicalEventType.INVENTORY_QUERY_ASKED,
            organization_id="o", project_id="p2", site_id=None, fields={"material_name": "cement"},
        )

    service = _Service({"gv": 117.0})
    many = event()
    await _inject_inventory_context(many, service, "Asia/Kolkata", SITES)
    assert many.fields["inventory_levels"][0]["current_stock"] == 117.0
    one = event()
    service.table = {}
    await _inject_inventory_context(one, service, "Asia/Kolkata", None)  # guard: scope as before
    assert one.fields["inventory_levels"] == [] and "inventory_by_site" not in one.fields
