"""The agent's tools: names, argument schemas and the understanding each one
stands for. Pure data and mapping -- nothing here touches I/O.

Every tool maps onto a `SemanticType` the classic pipeline already handles, with
the field names its extraction prompt documents (platform/ai Gemini adapter), so
canonicalization, the gates and the workflows read exactly what they always have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from canonicalization.question_note import question_note_candidate
from mesiri_ai.models import ToolSpec
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType

# Tool names (also the model-facing API).
SAVE_LABOUR = "save_labour"
SAVE_WORK_DONE = "save_work_done"
SAVE_MATERIAL_RECEIPT = "save_material_receipt"
SAVE_MATERIAL_USAGE = "save_material_usage"
SAVE_EXPENSE = "save_expense"
REPORT_ISSUE = "report_issue"
TRANSFER_MONEY = "transfer_money"
UNDO_LAST = "undo_last"
ASK_USER = "ask_user"
NOTE_FOR_ENGINEER = "note_for_engineer"
SET_UNIT_CONVERSION = "set_unit_conversion"
QUERY_LABOUR = "query_labour"
QUERY_MATERIALS = "query_materials"
QUERY_WORK_LOG = "query_work_log"
QUERY_PROJECT = "query_project"
QUERY_EXPENSES = "query_expenses"
REQUEST_DPR = "request_dpr"
# WA-45: where they work today, and new sites/projects.
SET_WORK_SITE = "set_work_site"
CREATE_SITE = "create_site"
CREATE_PROJECT = "create_project"

#: Tools that write a record (or an undo of one). A run that has attempted one
#: must never be retried from the top.
WRITE_TOOLS = frozenset(
    {
        SAVE_LABOUR,
        SAVE_WORK_DONE,
        SAVE_MATERIAL_RECEIPT,
        SAVE_MATERIAL_USAGE,
        SAVE_EXPENSE,
        REPORT_ISSUE,
        NOTE_FOR_ENGINEER,
        TRANSFER_MONEY,
        UNDO_LAST,
        SET_UNIT_CONVERSION,
        CREATE_SITE,
        CREATE_PROJECT,
    }
)

#: Tools that read. Their reply text is handed to the model to put in its answer.
QUERY_TOOLS = frozenset(
    {QUERY_LABOUR, QUERY_MATERIALS, QUERY_WORK_LOG, QUERY_PROJECT, QUERY_EXPENSES, REQUEST_DPR}
)

#: ARCH-04: set only after the user said yes to adding it to the material list.
_NEW_MATERIAL = {
    "type": "boolean",
    "description": "Only true after the user said yes to adding this as a new material.",
}

_DATE = {
    "type": "string",
    "description": (
        "The day it happened, ONLY when the message says so: 'yesterday', 'today', "
        "'day before yesterday' or an ISO date YYYY-MM-DD. Omit otherwise (never guess)."
    ),
}
_PROJECT = {
    "type": "string",
    "description": "Project name, ONLY if the user names one. Omit to use their usual project.",
}
_SITE = {
    "type": "string",
    "description": "Site name, ONLY if the user names one. Omit to use their usual site.",
}
_RANGE = {
    "type": "string",
    "enum": ["today", "this_week", "this_month"],
    "description": "The period asked about; omit if none is stated.",
}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def tool_specs() -> list[ToolSpec]:
    """The tools handed to the model, in the order shown to it."""
    return [
        ToolSpec(
            name=SAVE_LABOUR,
            description=(
                "Save who worked on site (attendance / headcount). One call per message "
                "covers every trade and named worker mentioned. Never invent a name. Not for "
                "a complaint that too few came ('only 4 masons came, short of labour'): that is "
                "report_issue with LABOUR_SHORTAGE."
            ),
            parameters=_obj(
                {
                    "workers": {
                        "type": "array",
                        "description": (
                            "One entry per named person or per trade group, e.g. "
                            "[{name:'Ravi',trade:'mason'},{trade:'helper',headcount:12}]."
                        ),
                        "items": _obj(
                            {
                                "name": {"type": "string", "description": "Omit for a group."},
                                "trade": {"type": "string"},
                                "headcount": {
                                    "type": "integer",
                                    "description": "People in this line; 1 for a named person.",
                                },
                                "daily_wage": {"type": "number"},
                                "attendance_status": {
                                    "type": "string",
                                    "enum": ["present", "absent", "half_day"],
                                },
                            }
                        ),
                    },
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                    "contractor": {"type": "string"},
                },
                ["workers"],
            ),
        ),
        ToolSpec(
            name=SAVE_WORK_DONE,
            description=(
                "Save work done or in progress on site (e.g. '180 sqm plastering done on "
                "2nd floor'). Not for problems or delays (use report_issue)."
            ),
            parameters=_obj(
                {
                    "narrative": {
                        "type": "string",
                        "description": "The report in the sender's own words.",
                    },
                    "work_type": {
                        "type": "string",
                        "description": (
                            "The kind of work, in English and short (plastering, concreting, "
                            "brickwork, wiring), whatever language the message is in "
                            "(തേപ്പ് / thepp -> plastering)."
                        ),
                    },
                    "quantities": {
                        "type": "array",
                        "items": _obj(
                            {
                                "work_type": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string", "description": "sqm, m3, nos, m ..."},
                            }
                        ),
                    },
                    "location": {"type": "string", "description": "Place on site, if stated."},
                    "continues": {
                        "type": "string",
                        "description": (
                            "When this continues or finishes work listed under 'Open work', its name "
                            "exactly as listed ('plastering finished' after 'started plastering'). "
                            "Omit for new work."
                        ),
                    },
                    "progress_percent": {
                        "type": "number",
                        "description": (
                            "How much of this work is done, when the message gives a "
                            "percentage ('40% aayi', '40 percent done' -> 40). Omit otherwise. "
                            "A percentage below 100 is never update_kind 'completed'."
                        ),
                    },
                    "update_kind": {
                        "type": "string",
                        "enum": ["started", "progress", "paused", "resumed", "completed"],
                        "description": (
                            "'completed' when the work is said to be finished (done, finished, "
                            "theernnu, kazhinju, ho gaya), unless a percentage below 100 is given; "
                            "'started' when it began (thudangi, shuru). Omit if genuinely unclear."
                        ),
                    },
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["narrative"],
            ),
        ),
        ToolSpec(
            name=SAVE_MATERIAL_RECEIPT,
            description=(
                "Save material that arrived / was delivered to site (came, arrived, vannu, "
                "eththi, aaya). Call it with the unit as said; the system checks the unit."
            ),
            parameters=_obj(
                {
                    "material": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {
                        "type": "string",
                        "description": (
                            "The unit said, in English: bags (chakk, ചാക്ക്, bori), kg, tons, cum, "
                            "nos, load (lorry, tipper), cft ..."
                        ),
                    },
                    "supplier": {"type": "string", "description": "Only if stated."},
                    "new_material": _NEW_MATERIAL,
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["material", "quantity", "unit"],
            ),
        ),
        ToolSpec(
            name=SAVE_MATERIAL_USAGE,
            description=(
                "Save material that was used / consumed on site (used, use cheythu, use aayi, "
                "laga). Call it with the unit as said; the system checks the unit."
            ),
            parameters=_obj(
                {
                    "material": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "work_item": {"type": "string", "description": "What it was used for."},
                    "new_material": _NEW_MATERIAL,
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["material", "quantity", "unit"],
            ),
        ),
        ToolSpec(
            name=SAVE_EXPENSE,
            description="Record money spent (paid to a vendor or for something). Asks to confirm.",
            parameters=_obj(
                {
                    "amount": {"type": "number"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "vendor": {"type": "string"},
                    "paid_to": {"type": "string"},
                    "date": _DATE,
                    "project": _PROJECT,
                },
                ["amount"],
            ),
        ),
        ToolSpec(
            name=REPORT_ISSUE,
            description=(
                "Report a problem, delay or blocker on site (ran out of cement, JCB broke "
                "down, rain stopped work). Not for work done."
            ),
            parameters=_obj(
                {
                    "issue_type": {
                        "type": "string",
                        "enum": [
                            "WEATHER",
                            "MATERIAL_SHORTAGE",
                            "LABOUR_SHORTAGE",
                            "DRAWING_PENDING",
                            "EQUIPMENT_BREAKDOWN",
                            "INSPECTION_WAITING",
                            "ACCESS",
                            "OTHER",
                        ],
                    },
                    "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "narrative": {"type": "string"},
                    "delay_duration_minutes": {"type": "integer"},
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["issue_type", "narrative"],
            ),
        ),
        ToolSpec(
            name=NOTE_FOR_ENGINEER,
            description=(
                "Pass a question to the user's engineer. ONLY when the user asks for it "
                "('engineer-inodu chodikku', 'ask the engineer ...'). Any other question you "
                "answer yourself from the facts or the query tools, or say plainly that the "
                "records cannot answer it. Never for a problem or delay (report_issue) and "
                "never for work done."
            ),
            parameters=_obj(
                {
                    "question": {
                        "type": "string",
                        "description": "The question, in the user's own words.",
                    },
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["question"],
            ),
        ),
        ToolSpec(
            name=SET_UNIT_CONVERSION,
            description=(
                "Remember, for the whole company, how many of a unit make one stock unit of a "
                "material ('28 bags of sand make 1 m³': material 'sand', unit 'bags', count 28). "
                "Only after a tool said the material is counted in another unit and the user "
                "gave that number. Then save their entry again with their own amount and unit."
            ),
            parameters=_obj(
                {
                    "material": {"type": "string"},
                    "unit": {"type": "string", "description": "The unit they reported in, e.g. bags."},
                    "count": {"type": "number", "description": "How many of that unit make ONE stock unit."},
                },
                ["material", "unit", "count"],
            ),
        ),
        ToolSpec(
            name=TRANSFER_MONEY,
            description="Move money between two of the company's accounts. Asks to confirm.",
            parameters=_obj(
                {
                    "amount": {"type": "number"},
                    "from_account": {"type": "string"},
                    "to_account": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["amount"],
            ),
        ),
        ToolSpec(
            name=UNDO_LAST,
            description=(
                "Undo the user's most recent saved entry ('undo', 'delete that', 'cancel the "
                "last expense'). Default undoes their latest saved update."
            ),
            parameters=_obj(
                {
                    "what": {
                        "type": "string",
                        "enum": ["latest_update", "expense", "transfer", "petty_cash"],
                        "description": "Omit for the latest saved update.",
                    }
                }
            ),
        ),
        ToolSpec(
            name=ASK_USER,
            description=(
                "Ask the user ONE question when you cannot tell what they mean or something "
                "needed is missing, instead of guessing. Ends your turn; their answer comes "
                "as their next message. Give 2-3 short options when the answer is a choice."
            ),
            parameters=_obj(
                {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "At most 10; 3 or fewer are shown as buttons.",
                    },
                },
                ["question"],
            ),
        ),
        ToolSpec(
            name=QUERY_LABOUR,
            description="Answer 'how many workers / who worked / labour cost' from saved records.",
            parameters=_obj(
                {
                    "date_range": _RANGE,
                    "trade": {"type": "string"},
                    "project": _PROJECT,
                    "site": _SITE,
                }
            ),
        ),
        ToolSpec(
            name=QUERY_MATERIALS,
            description=(
                "How much of a material is in stock now, with all-time received and used "
                "totals (all materials if none named). It has NO per-day figures: asked how "
                "much was used or received on one day, say you can only see the totals so far."
            ),
            parameters=_obj({"material": {"type": "string"}, "project": _PROJECT, "site": _SITE}),
        ),
        ToolSpec(
            name=QUERY_WORK_LOG,
            description="Answer what was logged / open site issues (the site log).",
            parameters=_obj(
                {
                    "date_range": _RANGE,
                    "work_type": {"type": "string"},
                    "project": _PROJECT,
                    "site": _SITE,
                }
            ),
        ),
        ToolSpec(
            name=QUERY_PROJECT,
            description="Summary / status of a project or site.",
            parameters=_obj({"project": _PROJECT, "site": _SITE}),
        ),
        ToolSpec(
            name=QUERY_EXPENSES,
            description="Answer account balance or past spending questions.",
            parameters=_obj(
                {
                    "kind": {"type": "string", "enum": ["balance", "expenses"]},
                    "account": {"type": "string"},
                    "category": {"type": "string"},
                    "date_range": _RANGE,
                    "missing_receipts": {
                        "type": "boolean",
                        "description": "True only when asking which expenses lack a receipt.",
                    },
                    "project": _PROJECT,
                },
                ["kind"],
            ),
        ),
        ToolSpec(
            name=REQUEST_DPR,
            description=(
                "Send the user a Daily Progress Report as a document: today's, or another "
                "day's when they name one ('yesterday's report', 'report for 12 Oct')."
            ),
            parameters=_obj({"date": _DATE, "project": _PROJECT, "site": _SITE}),
        ),
        ToolSpec(
            name=SET_WORK_SITE,
            description=(
                "The user says where they are working now or today ('now at Site B', "
                "'today Green Villa site', 'innu Site A-il'). Everything after is for that site "
                "until the day ends. Only for one of their own sites; to make a new one use "
                "create_site."
            ),
            parameters=_obj(
                {
                    "site": {"type": "string", "description": "The site name they said."},
                    "project": _PROJECT,
                },
                ["site"],
            ),
        ),
        ToolSpec(
            name=CREATE_SITE,
            description=(
                "Add a NEW site to a project, only when the user asks to create / add / start "
                "a new site. The user confirms with Yes before it is made."
            ),
            parameters=_obj(
                {
                    "name": {"type": "string", "description": "The new site's name, as they said it."},
                    "project": {
                        "type": "string",
                        "description": "Project it belongs to, ONLY if the user names one.",
                    },
                    "location": {"type": "string", "description": "Only if they say where it is."},
                },
                ["name"],
            ),
        ),
        ToolSpec(
            name=CREATE_PROJECT,
            description=(
                "Create a NEW project, only when the user asks to create / add / start a new "
                "project. The user confirms with Yes before it is made; adding its sites is "
                "offered after."
            ),
            parameters=_obj(
                {
                    "name": {"type": "string", "description": "The new project's name, as they said it."},
                    "location": {"type": "string", "description": "Only if they say where it is."},
                },
                ["name"],
            ),
        ),
    ]


@dataclass(frozen=True, slots=True)
class ScopeLookup:
    """The sender's own projects and sites (already scoped to their company),
    used to turn a name the user said into the id the pipeline validates."""

    projects: tuple[tuple[str, str], ...] = ()  # (id, name)
    sites: tuple[tuple[str, str, str | None], ...] = ()  # (id, name, project_id)

    @staticmethod
    def _match(rows: list[tuple[str, str]], wanted: str) -> str | None:
        key = wanted.strip().casefold()
        if not key:
            return None
        exact = [rid for rid, name in rows if name.strip().casefold() == key]
        if len(exact) == 1:
            return exact[0]
        partial = [rid for rid, name in rows if key in name.casefold() or name.casefold() in key]
        return partial[0] if len(partial) == 1 else None

    def project_id(self, name: str) -> str | None:
        return self._match([(pid, pname) for pid, pname in self.projects], name)

    def site_id(self, name: str, project_id: str | None = None) -> str | None:
        rows = [(sid, sname) for sid, sname, pid in self.sites if project_id in (None, pid)]
        return self._match(rows, name)


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values: the pipeline reads a missing key as 'not stated'."""
    return {k: v for k, v in fields.items() if v is not None and v != "" and v != []}


def _scope(args: dict[str, Any], scope: ScopeLookup) -> dict[str, Any]:
    """project/site the user named -> id when it is one of theirs, else the
    name as said (the context resolver validates it and the gates ask)."""
    out: dict[str, Any] = {}
    project = str(args.get("project") or "").strip()
    site = str(args.get("site") or "").strip()
    project_id = scope.project_id(project) if project else None
    if project:
        out["project_id" if project_id else "project_name"] = project_id or project
    if site:
        site_id = scope.site_id(site, project_id)
        out["site_id" if site_id else "site_name"] = site_id or site
    return out


def to_candidate(name: str, args: dict[str, Any], scope: ScopeLookup) -> Candidate | None:
    """The understanding a tool call stands for, or None for a tool that is not
    a workflow (ask_user, undo_last)."""
    sc = _scope(args, scope)
    date = args.get("date")
    if name == SAVE_LABOUR:
        fields = {
            "workers": args.get("workers"),
            "contractor": args.get("contractor"),
            "occurred_on": date,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.LABOUR_UPDATE, fields=_clean(fields))
    if name == SAVE_WORK_DONE:
        fields = {
            "narrative": args.get("narrative"),
            "work_type": args.get("work_type"),
            "quantities": args.get("quantities"),
            "location": args.get("location"),
            "update_kind": args.get("update_kind"),
            "progress_percent": args.get("progress_percent"),
            "continues": args.get("continues"),
            "occurred_on": date,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.GENERAL_SITE_UPDATE, fields=_clean(fields))
    if name in (SAVE_MATERIAL_RECEIPT, SAVE_MATERIAL_USAGE):
        received = name == SAVE_MATERIAL_RECEIPT
        fields = {
            "material_name": args.get("material"),
            "quantity": args.get("quantity"),
            "unit": args.get("unit"),
            "direction": "received" if received else "used",
            "supplier": args.get("supplier") if received else None,
            "work_item": None if received else args.get("work_item"),
            "occurred_on": date,
            "new_material": True if args.get("new_material") is True else None,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.MATERIAL_UPDATE, fields=_clean(fields))
    if name == SAVE_EXPENSE:
        fields = {
            "amount": args.get("amount"),
            "description": args.get("description"),
            "category": args.get("category"),
            "vendor": args.get("vendor"),
            "paid_to": args.get("paid_to"),
            "occurred_on": date,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.EXPENSE, fields=_clean(fields))
    if name == REPORT_ISSUE:
        fields = {
            "issue_type": args.get("issue_type"),
            "severity": args.get("severity"),
            "narrative": args.get("narrative"),
            "delay_duration_minutes": args.get("delay_duration_minutes"),
            "occurred_on": date,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.SITE_ISSUE, fields=_clean(fields))
    if name == NOTE_FOR_ENGINEER:
        question = str(args.get("question") or "").strip()
        if not question:
            return None
        note = question_note_candidate(question)
        fields = {**note.fields, "occurred_on": date, **sc}
        return Candidate(semantic_type=SemanticType.SITE_ISSUE, fields=_clean(fields))
    if name == TRANSFER_MONEY:
        fields = {
            "amount": args.get("amount"),
            "from_account_name": args.get("from_account"),
            "to_account_name": args.get("to_account"),
            "description": args.get("description"),
        }
        return Candidate(semantic_type=SemanticType.TRANSFER, fields=_clean(fields))
    if name == QUERY_LABOUR:
        fields = {"date_range": args.get("date_range"), "trade": args.get("trade"), **sc}
        return Candidate(semantic_type=SemanticType.LABOUR_QUERY, fields=_clean(fields))
    if name == QUERY_MATERIALS:
        fields = {"material_name": args.get("material"), **sc}
        return Candidate(semantic_type=SemanticType.INVENTORY_QUERY, fields=_clean(fields))
    if name == QUERY_WORK_LOG:
        fields = {"date_range": args.get("date_range"), "work_type": args.get("work_type"), **sc}
        return Candidate(semantic_type=SemanticType.ACTIVITY_QUERY, fields=_clean(fields))
    if name == QUERY_PROJECT:
        return Candidate(semantic_type=SemanticType.PROJECT_DETAIL_QUERY, fields=_clean(dict(sc)))
    if name == QUERY_EXPENSES:
        fields = {
            "query_kind": args.get("kind"),
            "account_name": args.get("account"),
            "category_name": args.get("category"),
            "date_range": args.get("date_range"),
            "missing_receipts": True if args.get("missing_receipts") else None,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.FINANCE_QUERY, fields=_clean(fields))
    if name == REQUEST_DPR:
        return Candidate(
            semantic_type=SemanticType.DPR_REQUEST,
            fields=_clean({"report_date": date, **sc}),
        )
    if name == CREATE_SITE:
        fields = {
            "name": str(args.get("name") or "").strip(),
            "location": args.get("location"),
            # The project it goes under; the new site's own name is never a
            # site to look up.
            **_scope({"project": args.get("project")}, scope),
        }
        return Candidate(semantic_type=SemanticType.SITE_CREATE, fields=_clean(fields))
    if name == CREATE_PROJECT:
        fields = {"name": str(args.get("name") or "").strip(), "location": args.get("location")}
        return Candidate(semantic_type=SemanticType.PROJECT_CREATE, fields=_clean(fields))
    if name == UNDO_LAST:
        what = str(args.get("what") or "latest_update")
        if what == "latest_update":
            return None
        return Candidate(semantic_type=SemanticType.REVERSAL, fields={"target_kind": what})
    return None
