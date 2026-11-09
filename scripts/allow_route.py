#!/usr/bin/env python3
"""TM-30: give the WhatsApp assistant (v3) a route the web dashboard already has, in one step.

    python3 scripts/allow_route.py GET /expenses/{expense_id} expense_detail "One expense with its bill photo."
    python3 scripts/allow_route.py POST /expenses/categories add_category "Prepare a new expense category." --ref '#a83836'

Checks the route is in the assistant's own API (the routers the live app mounts), refuses what must stay with a
person (anything that grants access: users, members, roles, settings, login; deletes; admin; Attendance / Payroll /
Workforce writes), then adds it to ALLOWED in apps/whatsapp-assistant/src/agent_api/tools.py and writes
tests/agent_api/test_allowed_<name>.py (the tool builds from the real OpenAPI; a write waits for Save). Run the
CLAUDE.md checks and push as usual; add an SOP.md line only if the model needs one to use it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _q(value: str) -> str:
    """A double-quoted Python string literal for ``value`` (apostrophes kept as they are)."""
    return json.dumps(value, ensure_ascii=False)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "whatsapp-assistant"
TOOLS = APP / "src" / "agent_api" / "tools.py"
TESTS = APP / "tests" / "agent_api"
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")

#: Routes that stay with a person (CLAUDE.md: access, security, held modules). Matched on the path.
REFUSED = [
    (re.compile(r"/(users|members|roles?|auth|login|invites?|access)(/|$)"), "it grants or changes access"),
    (re.compile(r"/settings(/|$)"), "company settings (modules, modes) stay with the Mesiri team"),
    (re.compile(r"^/admin(/|$)|^/claude-ops"), "admin routes"),
    (re.compile(r"/(payroll|wages?|salar(y|ies))(/|$)"), "Payroll needs the owner"),
]
HELD_WRITES = [(re.compile(r"^/labour/(attendance|workers)"), "Attendance / Workforce writes need the owner")]


#: The one refusal an owner-approved plan may lift (--owner-approved): a route that grants access.
ACCESS = REFUSED[0][1]


def refusal(method: str, path: str, *, owner_approved: bool = False) -> str | None:
    if method == "DELETE":
        return "deletes stay on the dashboard"
    for pattern, why in REFUSED:
        if pattern.search(path) and not (owner_approved and why == ACCESS):
            return why
    if method != "GET":
        for pattern, why in HELD_WRITES:
            if pattern.search(path):
                return why
    return None


def api_operation(method: str, path: str) -> dict | None:
    sys.path[:0] = [str(APP / "src"), str(ROOT / "backend" / "src"), str(ROOT / "platform" / "ai" / "src"),
                    str(ROOT / "shared" / "contracts" / "src")]
    from agent_api.app import build_api_app

    return build_api_app(None).openapi().get("paths", {}).get(path, {}).get(method.lower())


def add_to_tools(text: str, method: str, path: str, name: str, description: str, ref: str) -> str:
    if re.search(rf'Allowed\(\s*"{re.escape(name)}"', text):
        raise SystemExit(f"{name} is already on ALLOWED")
    if re.search(rf'"{re.escape(method)}", "{re.escape(path)}"', text):
        raise SystemExit(f"{method} {path} is already on ALLOWED")
    end = text.index("\n)\n", text.index("ALLOWED: tuple[Allowed, ...] = ("))
    desc = description.strip().rstrip(".") + "."
    write = " + _WRITE" if method != "GET" else ""
    # Double-quoted literals (the file's style) built with json.dumps, never by swapping quote characters: that
    # turned every apostrophe into a stray '"' ("each module"s own tool" broke tools.py, NXT-08).
    entry = (f"\n    # TM-30{f' ({ref})' if ref else ''}: the dashboard's own route, added by scripts/allow_route.py.\n"
             f"    Allowed({_q(name)}, {_q(method)}, {_q(path)}, {_q(desc)}{write}),")
    return text[:end] + entry + text[end:]


def test_file(method: str, path: str, name: str) -> str:
    return f'''"""TM-30: {method} {path} is a v3 tool ({name}), added by scripts/allow_route.py."""

from __future__ import annotations

from agent_api.app import build_api_app
from agent_api.tools import ALLOWED, build_tools


def test_{name}_is_a_tool_from_the_real_api() -> None:
    tools = build_tools(build_api_app(None).openapi(), tuple(a for a in ALLOWED if a.name == "{name}"))
    tool = tools["{name}"]
    assert (tool.method, tool.path) == ("{method}", "{path}")
    assert tool.is_write is {method != "GET"}  # a write waits for the person's Save
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    parser.add_argument("path")
    parser.add_argument("name")
    parser.add_argument("description")
    parser.add_argument("--ref", default="", help="the request's reference, e.g. #a83836")
    parser.add_argument("--owner-approved", action="store_true",
                        help="an owner approved this access route in the plan named by --ref (the API checks who may)")
    args = parser.parse_args()
    if not _NAME.match(args.name):
        parser.error("name: lower_snake_case, 3-41 characters")
    if args.owner_approved and not args.ref:
        parser.error("--owner-approved needs --ref: the plan the owner approved")
    why = refusal(args.method, args.path, owner_approved=args.owner_approved)
    if why:
        print(f"Refused: {args.method} {args.path}: {why}. Plan it for an owner instead.", file=sys.stderr)
        return 2
    if api_operation(args.method, args.path) is None:
        print(f"{args.method} {args.path} is not in the assistant's API (agent_api/app.py mounts the routers).",
              file=sys.stderr)
        return 3
    TOOLS.write_text(add_to_tools(TOOLS.read_text(encoding="utf-8"), args.method, args.path, args.name,
                                  args.description, args.ref), encoding="utf-8")
    test = TESTS / f"test_allowed_{args.name}.py"
    test.write_text(test_file(args.method, args.path, args.name), encoding="utf-8")
    print(f"Added {args.name} to {TOOLS.relative_to(ROOT)}; test {test.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
