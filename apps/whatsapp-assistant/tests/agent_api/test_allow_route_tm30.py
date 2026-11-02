"""TM-30: scripts/allow_route.py gives v3 a dashboard route in one step, and refuses what stays with a person.
Guards: access (users, members, roles, settings, login), deletes, admin, Payroll and Attendance / Workforce writes
are refused; a route not in the API is refused; the same route or name twice is refused."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent_api import tools as tools_mod


def _script():
    path = Path(__file__).resolve().parents[4] / "scripts" / "allow_route.py"
    spec = importlib.util.spec_from_file_location("allow_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/projects/{project_id}/members"), ("PATCH", "/users/{user_id}"), ("PUT", "/organizations/settings"),
    ("DELETE", "/progress/activities/{activity_id}"), ("GET", "/admin/requests"), ("POST", "/labour/attendance"),
    ("PATCH", "/labour/workers/{worker_id}"),
])
def test_what_stays_with_a_person_is_refused(method, path) -> None:
    assert _script().refusal(method, path)


@pytest.mark.parametrize(("method", "path"), [("GET", "/expenses/{expense_id}"), ("GET", "/labour/workers"),
                                              ("POST", "/expenses/categories")])
def test_ordinary_routes_pass(method, path) -> None:
    assert _script().refusal(method, path) is None


def test_the_entry_is_added_to_allowed_and_builds_from_the_real_api() -> None:
    script = _script()
    text = Path(tools_mod.__file__).read_text(encoding="utf-8")
    new = script.add_to_tools(text, "GET", "/expenses/{expense_id}", "expense_detail", "One expense", "#a83836")
    assert 'Allowed("expense_detail", "GET", "/expenses/{expense_id}", "One expense.")' in new
    assert "TM-30 (#a83836)" in new
    namespace: dict = {}
    exec(compile(new, "tools.py", "exec"), namespace)  # noqa: S102 -- the edited module still loads
    assert any(a.name == "expense_detail" for a in namespace["ALLOWED"])
    write = script.add_to_tools(text, "PATCH", "/expenses/categories/{category_id}", "rename_category", "A category", "")
    assert '"A category." + _WRITE' in write
    with pytest.raises(SystemExit):
        script.add_to_tools(text, "GET", "/projects", "projects_again", "x", "")  # the route is already there
    assert script.api_operation("GET", "/expenses/{expense_id}") is not None
    assert script.api_operation("GET", "/nope") is None
