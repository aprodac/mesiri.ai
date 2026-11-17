"""SS-74d: which rows a save point takes, and the order it puts them back in (pure, from a made-up catalogue)."""

from __future__ import annotations

import pytest

from mesiri.application.learn.sandbox_days import layout_from


def _link(child, col, parent, *, nullable=True, ref="id", width=1):
    return {"child": child, "col": col, "parent": parent, "ref": ref, "nullable": nullable, "width": width}


def _cols(*tables):
    return [{"t": t, "col": c, "generated": False, "pk": c == "id"} for t in tables for c in ("id", "x")]


ORG = {"projects", "sites", "receipts", "usage", "reports", "users", "admin_audit_log", "sandbox_days", "organizations"}
LINKS = [
    _link("sites", "project_id", "projects", nullable=False),
    _link("site_members", "site_id", "sites", nullable=False),  # no organization_id: comes with its site
    _link("site_members", "user_id", "users", nullable=False),
    _link("receipts", "reverses_id", "usage"),  # an optional loop between two tables
    _link("usage", "reverses_id", "receipts"),
    _link("report_versions", "report_id", "reports", nullable=False),  # a required link one way...
    _link("reports", "current_version_id", "report_versions"),  # ...an optional one back
    _link("projects", "parent_id", "projects"),  # a table pointing at itself
    _link("tokens", "user_id", "users", nullable=False),  # only the people's: not the company's records
]
TABLES = ("projects", "sites", "site_members", "receipts", "usage", "reports", "report_versions")


def test_takes_the_company_tables_and_what_hangs_off_them_not_people_or_logs():
    lay = layout_from(ORG, LINKS, _cols(*TABLES))
    assert set(lay.order) == set(TABLES)
    assert lay.where["sites"] == "organization_id = :o"
    assert '"site_id" IN (SELECT "id" FROM "sites" WHERE organization_id = :o)' in lay.where["site_members"]
    assert '"user_id" IN (SELECT "id" FROM "users" WHERE organization_id = :o)' in lay.where["site_members"]


def test_parents_first_and_loops_filled_in_after():
    lay = layout_from(ORG, LINKS, _cols(*TABLES))
    pos = {t: i for i, t in enumerate(lay.order)}
    assert pos["projects"] < pos["sites"] < pos["site_members"]
    assert pos["reports"] < pos["report_versions"]  # the required link decides the order
    assert lay.loops == {"receipts": ("reverses_id",), "usage": ("reverses_id",), "reports": ("current_version_id",)}
    assert "projects" not in lay.loops  # a table's own links hold within its one insert


def test_a_loop_of_required_links_is_refused_not_guessed():
    links = [_link("a", "b_id", "b", nullable=False), _link("b", "a_id", "a", nullable=False)]
    with pytest.raises(RuntimeError, match="loop"):
        layout_from({"a", "b"}, links, _cols("a", "b"))
