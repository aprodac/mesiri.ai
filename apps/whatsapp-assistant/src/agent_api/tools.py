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
#: words, naming the change they are asked to confirm.
SUMMARY_ARG = "summary"


@dataclass(frozen=True)
class Allowed:
    """One API route the agent may use, under a short name, with what it is for."""

    name: str
    method: str
    path: str
    description: str


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

    @property
    def is_write(self) -> bool:
        return self.method != "GET"


# The materials pilot. Adding a module is adding its routes here.
ALLOWED: tuple[Allowed, ...] = (
    Allowed("list_projects", "GET", "/projects", "The projects this person can see."),
    Allowed("list_sites", "GET", "/projects/{project_id}/sites", "The sites of one project."),
    Allowed(
        "search_materials", "GET", "/materials",
        "Find materials in the company's catalog by name (search). Gives each material's id and default unit.",
    ),
    Allowed("list_units", "GET", "/materials/units-of-measure", "Units of measure (bag, kg, nos, ton, ...) and their ids."),
    Allowed(
        "stock_levels", "GET", "/materials/inventory",
        "Current stock per site and material. Filter by project, site or material.",
    ),
    Allowed("stock_check", "GET", "/materials/stock-check", "Current stock of one material at one site."),
    Allowed(
        "list_receipts", "GET", "/materials/inflows",
        "Materials received: who recorded what, where and when. Use for 'what came today'.",
    ),
    Allowed(
        "list_usage", "GET", "/materials/outflows",
        "Materials used or issued: who recorded what, where and when.",
    ),
    Allowed(
        "record_receipt", "POST", "/materials/inflows",
        "Prepare a material receipt (material that arrived at a site). Saved only after the person confirms.",
    ),
    Allowed(
        "record_usage", "POST", "/materials/outflows",
        "Prepare a material usage (material used or issued at a site). Saved only after the person confirms.",
    ),
    Allowed(
        "record_transfer", "POST", "/materials/transfers",
        "Prepare a transfer of material from one site to another. Saved only after the person confirms.",
    ),
)


class ToolBuildError(RuntimeError):
    """An allowed route is not in the API (renamed or removed)."""


def build_tools(openapi: dict[str, Any], allowed: tuple[Allowed, ...] = ALLOWED) -> dict[str, ApiTool]:
    """The tools for ``allowed``, read from the app's OpenAPI document."""
    components = openapi.get("components", {}).get("schemas", {})
    tools: dict[str, ApiTool] = {}
    for item in allowed:
        operation = openapi.get("paths", {}).get(item.path, {}).get(item.method.lower())
        if operation is None:
            raise ToolBuildError(f"{item.method} {item.path} is not in the API")
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
                properties[name] = schema
                body_fields.append(name)
            required.extend(n for n in body.get("required", []) if n not in required)
        if item.method != "GET":
            properties[SUMMARY_ARG] = {
                "type": "string",
                "description": "One line in the person's words naming this entry, shown when they confirm.",
            }
            required.append(SUMMARY_ARG)
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
