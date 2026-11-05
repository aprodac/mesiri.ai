"""WA-119: the agent's tools are the app's own API routes, read from its OpenAPI.

Nothing here knows what a material receipt is. Each tool is one route the web
dashboard already calls; its arguments are the route's path and query
parameters plus its JSON body fields, taken from the OpenAPI document so a
change to the API changes the tool with it (and the drift test fails if an
allowed route disappears).

Only routes on ``ALLOWED`` are tools. A ``GET`` runs at once; any other method
is a *write* and is held until the person confirms (see ``agent.py``).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from mesiri_ai.models import ToolSpec

#: Every write tool takes this extra argument: one line, in the person's own
#: words, naming the change they are asked to confirm. (Not "summary": the
#: issue API has a body field of that name.)
CONFIRM_ARG = "confirm_line"
#: [210]: a write that names a material by id also takes the person's own word for it, so the code can check the
#: id is that material (or a name the company taught it) and never another one that is merely near.
MATERIAL_SAID = "material_said"


@dataclass(frozen=True)
class Allowed:
    """One API route the agent may use, under a short name, with what it is for.

    ``hide``: body fields the model never sees (internal bookkeeping).
    ``fixed``: body fields always sent with this value (e.g. ``source``)."""

    name: str
    method: str
    path: str
    description: str
    hide: tuple[str, ...] = ()
    fixed: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class ApiTool:
    """A route turned into a tool: its spec for the model and how to call it."""

    name: str
    method: str
    path: str
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    body_fields: tuple[str, ...]
    spec: ToolSpec
    required: tuple[str, ...] = field(default_factory=tuple)
    fixed: tuple[tuple[str, Any], ...] = ()
    #: Body fields the API takes but the model never sees (some the code fills, e.g. a photo).
    hidden: tuple[str, ...] = ()

    @property
    def is_write(self) -> bool:
        return self.method != "GET"


_WRITE = " Saved only after the person confirms."

# Adding a module is adding its routes here (and its router to app.API_ROUTERS).
ALLOWED: tuple[Allowed, ...] = (
    # Projects and sites
    Allowed("list_projects", "GET", "/projects", "The projects this person can see."),
    Allowed("list_sites", "GET", "/projects/{project_id}/sites", "The sites of one project."),
    # What happened (any module)
    Allowed(
        "day_summary", "GET", "/timeline/day-summary",
        "What was reported on a day or date range, per site: work, labour, materials, issues, "
        "conditions, and who reported. Use for 'what happened today' and 'did anyone report X'.",
    ),
    Allowed("timeline", "GET", "/timeline", "The detailed list of events (who reported what, when), filterable by type."),
    # Materials
    Allowed(
        "search_materials", "GET", "/materials",
        "Find materials in the company's catalog by name (search). Gives each material's id and default unit.",
    ),
    Allowed("list_units", "GET", "/materials/units-of-measure", "Units of measure (bags, kg, pieces, tons, ...) and their ids."),
    Allowed(
        "stock_levels", "GET", "/materials/inventory",
        "Current stock per site and material. Filter by project, site or material.",
    ),
    Allowed("stock_check", "GET", "/materials/stock-check", "Current stock of one material at one site."),
    Allowed("list_receipts", "GET", "/materials/inflows", "Materials received: what, where, when, who recorded it."),
    Allowed("list_usage", "GET", "/materials/outflows", "Materials used or issued: what, where, when, who recorded it."),
    Allowed("record_receipt", "POST", "/materials/inflows", "Prepare a material receipt (material that arrived at a site)." + _WRITE),
    Allowed("record_usage", "POST", "/materials/outflows", "Prepare a material usage (material used or issued at a site)." + _WRITE),
    Allowed("record_transfer", "POST", "/materials/transfers", "Prepare a transfer of material from one site to another." + _WRITE),
    # Labour
    Allowed("labour_attendance", "GET", "/labour/attendance", "Labour attendance reported: per site and date, which trades, how many, who reported."),
    Allowed("list_workers", "GET", "/labour/workers", "The company's worker register (names, trades, wages). Use a worker's id for a named person."),
    Allowed(
        "record_attendance", "POST", "/labour/attendance",
        "Prepare a labour attendance report for one site and day: named workers and/or a headcount per trade. "
        "If that site and day already has a report, ask whether this replaces it (corrects_report_id) or is "
        "another crew." + _WRITE,
        hide=("recorded_via",), fixed=(("recorded_via", "whatsapp_text"),),
    ),
    # Work and issues
    Allowed("work_progress", "GET", "/progress/activities", "Work done / in progress per site, with dates and quantities."),
    Allowed(
        "record_work", "POST", "/progress/activities",
        "Prepare work done at a site on a day: what was done, and quantities in the unit they said." + _WRITE,
        hide=("source",), fixed=(("source", "whatsapp_text"),),
    ),
    Allowed("list_issues", "GET", "/progress/issues", "Site issues (problems, delays), open or closed."),
    Allowed("report_issue", "POST", "/progress/issues", "Prepare a site issue (a problem or delay at a site)." + _WRITE),
    Allowed("resolve_issue", "POST", "/progress/issues/{issue_id}/resolve", "Prepare closing an issue as fixed." + _WRITE),
    # Expenses
    Allowed("list_expenses", "GET", "/expenses", "Expenses recorded, per project or site."),
    Allowed("expense_categories", "GET", "/expenses/categories", "The company's expense categories and their ids."),
    Allowed("money_accounts", "GET", "/finance/accounts", "The company's money accounts (petty cash, bank) and balances."),
    Allowed("list_vendors", "GET", "/finance/vendors", "The company's vendors (shops, suppliers): names, how many expenses, total paid."),
    Allowed(
        "record_expense", "POST", "/expenses", "Prepare an expense (money spent), from words or a bill photo; the photo is attached by itself. "
        "Vendor and category as text, as they said or as the bill shows." + _WRITE,
        hide=("source", "source_message_id", "correlation_id", "media_object_key"), fixed=(("source", "whatsapp"),),
    ),
    # Site day: weather and conditions, the DPR
    Allowed("site_day", "GET", "/dpr/site-days/{site_id}", "One site's day: conditions (weather, hours lost), plan, what is reported."),
    Allowed(
        "set_site_conditions", "PATCH", "/dpr/site-days/{site_id}/conditions",
        "Prepare a site's conditions for a day: weather, hours lost, whether the site worked, tomorrow's plan." + _WRITE,
    ),
    Allowed("send_dpr", "POST", "/dpr/projects/{project_id}/send", "Prepare sending today's project DPR now." + _WRITE),
    # WA-142: corrections and set-up the dashboard already offers. Each one is prepared like any write
    # and runs only on Save, as the person (the API applies their role). Not here on purpose: anything
    # that grants access (users, roles; project members only as add_project_member below, approved by the owner
    # in [207]), Workforce / Attendance deletes, modules.
    Allowed("work_item", "GET", "/progress/activities/{activity_id}", "One work entry with its quantities and ids."),
    Allowed("correct_work", "PATCH", "/progress/activities/{activity_id}",
            "Prepare a correction of a work entry already saved (its quantity, description or date): find it with "
            "work_progress first." + _WRITE),
    Allowed("acknowledge_issue", "POST", "/progress/issues/{issue_id}/acknowledge",
            "Prepare marking an issue as seen / being handled." + _WRITE),
    Allowed("wont_fix_issue", "POST", "/progress/issues/{issue_id}/wont-fix",
            "Prepare closing an issue that will not be fixed (with the reason)." + _WRITE),
    Allowed("undo_receipt", "POST", "/materials/inflows/{receipt_id}/reverse",
            "Prepare taking back a material receipt saved by mistake (find it with list_receipts); then prepare the "
            "right one if they said it." + _WRITE),
    Allowed("undo_usage", "POST", "/materials/outflows/{usage_id}/reverse",
            "Prepare taking back a material usage saved by mistake (find it with list_usage)." + _WRITE),
    Allowed("undo_transfer", "POST", "/materials/transfers/{transfer_id}/reverse",
            "Prepare taking back a material transfer saved by mistake." + _WRITE),
    Allowed("undo_expense", "POST", "/expenses/{expense_id}/reverse",
            "Prepare taking back an expense saved by mistake (find it with list_expenses)." + _WRITE),
    # PRC-01: `category_id` stays hidden until PRC-02 lets the code pick the category; a guessed id
    # would fail the save.
    Allowed("add_material", "POST", "/materials",
            "Prepare adding a material to the company's list (name, default unit, other names it is called)." + _WRITE,
            hide=("category_id",)),
    Allowed("update_material", "PATCH", "/materials/{material_id}",
            "Prepare changing a material in the list: its name, default unit, or the other names it is called "
            "(aliases, e.g. 'kambi' for steel)." + _WRITE,
            hide=("category_id",)),
    Allowed("set_unit_conversion", "PUT", "/materials/{material_id}/unit-conversions",
            "Prepare setting, for the whole company, how much ONE of the unit they count in is in the material's "
            "stock unit (1 bar of TMT 12mm = 10.67 kg; 1 load of sand = 3 m3). Use when a line was refused because "
            "the material is stocked in another unit and they told you the size; the refused line then saves "
            "converted. Admin or project manager only." + _WRITE),
    # WA-168: sizes nobody on site knew, asked of the company's admins (the dashboard's Materials -> Sizes too).
    Allowed("size_requests", "GET", "/materials/size-requests",
            "The sizes the company was asked for (📏 Sizes needed): material, unit, lines waiting, any proposal, ids."),
    Allowed("answer_size_request", "POST", "/materials/size-requests/{request_id}/answer",
            "Prepare an admin's or project manager's answer to a size the company was asked for (\"M-sand load 60\": "
            "one_unit_equals = how many of the stock unit in ONE of that unit). On Save it is set for the whole "
            "company and every line that waited for it saves, converted." + _WRITE),
    # WA-169: the language this person's replies are always in (users.reply_language); the dashboard sets it too.
    Allowed("set_reply_language", "PUT", "/me/reply-language",
            "Set the language this person's replies are ALWAYS in, whatever they write in next: english, "
            "manglish (Malayalam in English letters), malayalam (Malayalam script), hindi, hinglish; auto = follow "
            "each message again. Only when they ask for it (\"always reply in Manglish\", \"English mathi\"). Set at "
            "once by the code: not a card line, nothing to save."),
    Allowed("add_expense_category", "POST", "/expenses/categories", "Prepare a new expense category." + _WRITE),
    Allowed("create_project", "POST", "/projects", "Prepare a new project (name, client, address, dates)." + _WRITE),
    Allowed("update_project", "PUT", "/projects/{project_id}",
            "Prepare changing a project's details (name, client, address, dates, status)." + _WRITE),
    Allowed("add_site", "POST", "/projects/{project_id}/sites", "Prepare a new site in a project." + _WRITE),
    Allowed("update_site", "PUT", "/projects/{project_id}/sites/{site_id}",
            "Prepare changing a site's details (name, address, status)." + _WRITE),
    # TM-30 ([207]): the dashboard's own route, added by scripts/allow_route.py.
    Allowed("add_project_member", "POST", "/projects/{project_id}/members", "Prepare adding a person who is already in the company to a project, with a role (site engineer, project manager, finance, admin). userId: their name as said is fine, the code finds them; role: as said." + _WRITE),
    # TM-30 ([210]): a new materials route (an alias), added by scripts/allow_route.py.
    Allowed("add_material_alias", "POST", "/materials/{material_id}/aliases",
            "Prepare remembering another name the company's people call a material (their word, any script: "
            "'primer' for Paint), so that word finds it next time. Use when they chose a material for a word that "
            "was not in the list." + _WRITE),
    # TM-30 (#230): the dashboard's own route, added by scripts/allow_route.py.
    Allowed("my_requests", "GET", "/me/requests", "The requests this person asked Mesiri for, and where each one is (asked, building, live, dropped)."),
)


class ToolBuildError(RuntimeError):
    """An allowed route is not in the API (renamed or removed), or clashes with the tool's own argument."""


def build_tools(openapi: dict[str, Any], allowed: tuple[Allowed, ...] = ALLOWED) -> dict[str, ApiTool]:
    """The tools for ``allowed``, read from the app's OpenAPI document."""
    components = openapi.get("components", {}).get("schemas", {})
    tools: dict[str, ApiTool] = {}
    for item in allowed:
        operation = openapi.get("paths", {}).get(item.path, {}).get(item.method.lower())
        if operation is None:
            raise ToolBuildError(f"{item.method} {item.path} is not in the API")
        hidden = set(item.hide) | {k for k, _ in item.fixed}
        properties: dict[str, Any] = {}
        required: list[str] = []
        path_params: list[str] = []
        query_params: list[str] = []
        for param in operation.get("parameters", []):
            where = param.get("in")
            if where not in ("path", "query"):
                continue  # headers (Idempotency-Key) are the client's, not the model's
            name = param["name"]
            schema = _clean(param.get("schema", {}), components)
            if param.get("description"):
                schema.setdefault("description", param["description"])
            properties[name] = schema
            (path_params if where == "path" else query_params).append(name)
            if param.get("required"):
                required.append(name)
        body_fields: list[str] = []
        body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        if body is not None:
            body = _clean(body, components)
            for name, schema in body.get("properties", {}).items():
                if name in hidden:
                    continue
                properties[name] = schema
                body_fields.append(name)
            required.extend(n for n in body.get("required", []) if n not in required and n not in hidden)
        if item.method != "GET":
            if CONFIRM_ARG in properties:
                raise ToolBuildError(f"{item.method} {item.path} has its own field named {CONFIRM_ARG}")
            properties[CONFIRM_ARG] = {
                "type": "string",
                "description": "One line in the person's words naming this entry, shown when they confirm.",
            }
            required.append(CONFIRM_ARG)
            if "material_id" in body_fields:
                properties[MATERIAL_SAID] = {
                    "type": "string",
                    "description": "The material exactly as the person said it, in their word and script "
                                   "('primer', 'kambi', 'സിമന്റ്'); the code checks material_id is that material.",
                }
        parameters: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required
        tools[item.name] = ApiTool(
            name=item.name,
            method=item.method,
            path=item.path,
            path_params=tuple(path_params),
            query_params=tuple(query_params),
            body_fields=tuple(body_fields),
            spec=ToolSpec(name=item.name, description=item.description, parameters=parameters),
            required=tuple(required),
            fixed=item.fixed,
            hidden=tuple(sorted(hidden)),
        )
    return tools


_KEEP = ("type", "format", "enum", "description", "items", "properties", "required", "minimum", "maximum")


def _clean(schema: dict[str, Any], components: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """The schema with ``$ref`` inlined, ``X | None`` read as ``X`` and only the
    keys every tool-calling provider accepts (no titles, no ``anyOf``)."""
    if depth > 8:
        return {"type": "object"}
    schema = copy.deepcopy(schema)
    ref = schema.pop("$ref", None)
    if ref is not None:
        target = components.get(ref.rsplit("/", 1)[-1], {})
        merged = {**target, **schema}
        return _clean(merged, components, depth + 1)
    for key in ("anyOf", "oneOf"):
        options = [o for o in schema.pop(key, []) if o.get("type") != "null"]
        if options:
            # Several real options (e.g. number | numeric string for a Decimal): the first.
            chosen = _clean(options[0], components, depth + 1)
            schema = {**chosen, **{k: v for k, v in schema.items() if k in _KEEP}}
    out: dict[str, Any] = {k: v for k, v in schema.items() if k in _KEEP}
    if "properties" in out:
        out["properties"] = {n: _clean(s, components, depth + 1) for n, s in out["properties"].items()}
        out.setdefault("type", "object")
    if "items" in out and isinstance(out["items"], dict):
        out["items"] = _clean(out["items"], components, depth + 1)
    if out.get("type") == "string" and out.get("format") not in (None, "date", "date-time"):
        out.pop("format")  # uuid, decimal ...: plain strings to the model
    if "type" not in out and "properties" not in out:
        out["type"] = "string"
    return out


def what_mesiri_does(tools: dict[str, ApiTool]) -> str:
    """[247] A short "What Mesiri does" block drawn from the tool list itself, so a new route is in it with no edit
    here. Three groups by what the route is: record (a write, saved on one Save tap), reports (the day, the DPR, the
    timeline) and ask (every other read). The model answers "what can Mesiri do" from it (SOP rule 11)."""
    groups: dict[str, list[str]] = {"record": [], "ask": [], "reports": []}
    for tool in tools.values():
        first = tool.spec.description.replace(_WRITE, "").split(". ")[0].strip().rstrip(".")
        line = f"{tool.name}: {first[:110]}"
        if tool.is_write:
            groups["record"].append(line)
        elif tool.path.startswith(("/dpr", "/timeline")):
            groups["reports"].append(line)
        else:
            groups["ask"].append(line)
    heads = {"record": "Record (the person sends it as a message, a voice note or a photo; one Save tap keeps it)",
             "ask": "Ask (answered from what is recorded: progress, issues, stock, attendance, expenses, materials)",
             "reports": "Reports (what happened on a day, the daily report, the timeline)"}
    return "What Mesiri does (from your tools, this is the whole list):\n" + "\n".join(
        f"{heads[g]}:\n" + "\n".join(f"- {line}" for line in lines) for g, lines in groups.items() if lines)
