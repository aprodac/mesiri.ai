"""The agent's tools: names, argument schemas and the understanding each one
stands for. Pure data and mapping -- nothing here touches I/O.

Every tool maps onto a `SemanticType` the classic pipeline already handles, with
the field names its extraction prompt documents (platform/ai Gemini adapter), so
canonicalization, the gates and the workflows read exactly what they always have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mesiri_ai.models import ToolSpec
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType

# Tool names (also the model-facing API).
SAVE_LABOUR = "save_labour"
SAVE_WORK_DONE = "save_work_done"
SAVE_MATERIAL_RECEIPT = "save_material_receipt"
SAVE_MATERIAL_USAGE = "save_material_usage"
# [103]: material sent to another site; stock that was on site before Mesiri.
TRANSFER_MATERIAL = "transfer_material"
SAVE_OPENING_STOCK = "save_opening_stock"
SAVE_EXPENSE = "save_expense"
REPORT_ISSUE = "report_issue"
TRANSFER_MONEY = "transfer_money"
UNDO_LAST = "undo_last"
# Request 142 (B): undo or change anything saved, from the journal.
CHANGE_OR_UNDO = "change_or_undo"
ASK_USER = "ask_user"
NOTE_FOR_ENGINEER = "note_for_engineer"
REQUEST_MATERIAL = "request_material"
SET_UNIT_CONVERSION = "set_unit_conversion"
QUERY_LABOUR = "query_labour"
QUERY_MATERIALS = "query_materials"
QUERY_WORK_LOG = "query_work_log"
QUERY_PROJECT = "query_project"
QUERY_EXPENSES = "query_expenses"
REQUEST_DPR = "request_dpr"
# WA-45: where they work today, and new sites/projects.
SET_WORK_SITE = "set_work_site"
SET_REPLY_LANGUAGE = "set_reply_language"
CREATE_SITE = "create_site"
CREATE_PROJECT = "create_project"
# 22 Oct: back from the classic pipeline.
ADD_MEMBER = "add_member"
# SET-07: the company join code, asked in any words.
GET_JOIN_CODE = "get_join_code"
CORRECT_WORK_QUANTITY = "correct_work_quantity"
UPDATE_ISSUE = "update_issue"
# Request 88: change one item of the card that is still open.
UPDATE_PENDING_CARD = "update_pending_card"
# Live 29 Oct: look at the photo they sent that is still waiting for its purpose.
LOOK_AT_PHOTO = "look_at_held_photo"
# WA-57: a part of the message that cannot be recorded this turn.
STILL_TO_DO = "still_to_do"
# Request 104, B: the day's weather, whether the site worked, tomorrow's plan.
SET_SITE_CONDITIONS = "set_site_conditions"

#: Tools that write a record (or an undo of one). A run that has attempted one
#: must never be retried from the top.
WRITE_TOOLS = frozenset(
    {
        SAVE_LABOUR,
        SAVE_WORK_DONE,
        SAVE_MATERIAL_RECEIPT,
        SAVE_MATERIAL_USAGE,
        TRANSFER_MATERIAL,
        SAVE_OPENING_STOCK,
        SAVE_EXPENSE,
        REPORT_ISSUE,
        NOTE_FOR_ENGINEER,
        REQUEST_MATERIAL,
        TRANSFER_MONEY,
        UNDO_LAST,
        CHANGE_OR_UNDO,
        SET_UNIT_CONVERSION,
        CREATE_SITE,
        CREATE_PROJECT,
        ADD_MEMBER,
        CORRECT_WORK_QUANTITY,
        UPDATE_ISSUE,
        UPDATE_PENDING_CARD,
        SET_SITE_CONDITIONS,
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
#: The classic "send it as a PDF" of a lookup (stock, labour, work log, money).
_AS_PDF = {"type": "boolean", "description": "Old way of asking for a PDF; use send_as."}
_SEND_AS = {
    "type": "string",
    "enum": ["text", "pdf", "image"],
    "description": (
        "How to send the answer. 'text' (default): a normal reply. 'pdf': they ask for a PDF or a "
        "file. 'image': they ask for it as an image, photo, picture or screenshot ('image aayittu', "
        "'photo aayittu', 'padam'). Lookups can always go as text, PDF or image: never say otherwise."
    ),
}
#: A bill names "Cement OPC 53 grade" or "TMT steel bars 12mm": the material is
#: the plain name (live photo set, 22 Oct: the full trade name matched nothing).
_MATERIAL = {
    "type": "string",
    "description": (
        "The plain material name, as in the company's materials (cement, steel, bricks, "
        "M sand); not a bill's trade name, grade or size."
    ),
}
_RANGE = {
    "type": "string",
    "enum": ["today", "this_week", "this_month"],
    "description": "The period asked about; omit if none is stated.",
}


_PERIOD = {
    "type": "string",
    "enum": ["today", "yesterday", "this_week", "last_week", "this_month"],
    "description": "The period asked about ('yesterday', 'this week'); omit if none is stated.",
}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


#: WA-57/58: one part of a message still to do (still_to_do, ask_user other_parts).
_LATER_ITEM = _obj(
    {
        "tool": {"type": "string", "description": "The save tool that will record it, e.g. save_labour."},
        "what": {
            "type": "string",
            "description": (
                "What they said about it, in a few English words, e.g. "
                "'scaffolders and plasterers came, no count yet'."
            ),
        },
    },
    ["what"],
)


#: The fields a correction may carry (update_pending_card, change_or_undo).
_CHANGES = _obj(
    {
        "workers": {
            "type": "array",
            "description": "Only the trade lines that change, e.g. [{trade:'mason',headcount:8}].",
            "items": _obj(
                {
                    "name": {"type": "string"},
                    "trade": {"type": "string"},
                    "headcount": {"type": "integer"},
                    "daily_wage": {"type": "number"},
                    "attendance_status": {
                        "type": "string",
                        "enum": ["present", "absent", "half_day"],
                    },
                }
            ),
        },
        "quantity": {"type": "number"},
        "unit": {"type": "string"},
        "material": {"type": "string"},
        "supplier": {"type": "string"},
        "work_item": {"type": "string"},
        "narrative": {"type": "string"},
        "work_type": {"type": "string"},
        "location": {"type": "string"},
        "progress_percent": {"type": "number"},
        "amount": {"type": "number"},
        "description": {"type": "string"},
        "vendor": {"type": "string"},
        "paid_to": {"type": "string"},
        "category": {"type": "string"},
        "severity": {"type": "string"},
        "date": _DATE,
    }
)


def look_at_photo_spec() -> ToolSpec:
    """Offered only on a turn where a photo is held (runtime/agent/runner.py)."""
    return ToolSpec(
        name=LOOK_AT_PHOTO,
        description=(
            "Look at the photo they sent that is still waiting for its purpose, and get what it "
            "shows. Call it when they ask about that photo ('what is this?', 'look at the photo', "
            "'ithenthaa?', 'noki nok'). It saves nothing. Then say what you see in one or two "
            "lines and ask what it is for (bill, attendance register, site update, expense), "
            "or answer their question about it. Never say you cannot see it."
        ),
        parameters=_obj({}),
    )


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
                    "location": {
                        "type": "string",
                        "description": (
                            "The floor or place on site, whenever the message gives one ('2nd floor', "
                            "'ground floor', 'terrace'): '3rd floor slab concreting finished' -> "
                            "location '3rd floor', work_type 'slab concreting'. Never leave it only "
                            "inside work_type."
                        ),
                    },
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
                            "'started' when it began (thudangi, shuru); 'progress' when a percentage "
                            "is given. Omit if genuinely unclear."
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
                    "material": _MATERIAL,
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
                    "material": _MATERIAL,
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
            name=TRANSFER_MATERIAL,
            description=(
                "Save material SENT FROM one site TO ANOTHER site of the company (sent to, shifted "
                "to, transferred, moved to site B, matti, kondupoyi, bheja). It takes stock off "
                "the sending site and adds it to the receiving one. Never save it as used, and "
                "not as received: the other site is named, so this is the tool. If only the "
                "sending site is named and it is where they work, the receiving one is still "
                "needed: ask. Call it with the unit as said; the system checks the unit."
            ),
            parameters=_obj(
                {
                    "material": _MATERIAL,
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "to_site": {
                        "type": "string",
                        "description": "The site the material went TO, as said. Never a guess.",
                    },
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": {
                        "type": "string",
                        "description": (
                            "The site it was sent FROM, ONLY if the user names one. Omit to use "
                            "their usual site."
                        ),
                    },
                },
                ["material", "quantity", "unit", "to_site"],
            ),
        ),
        ToolSpec(
            name=SAVE_OPENING_STOCK,
            description=(
                "Save stock that was ALREADY on site before they started using Mesiri (opening "
                "stock, already on site, stock undayirunnu, before Mesiri, starting stock). Never "
                "a delivery: use this, not save_material_receipt. Entered once per site and "
                "material. Call it with the unit as said; the system checks the unit."
            ),
            parameters=_obj(
                {
                    "material": _MATERIAL,
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "new_material": _NEW_MATERIAL,
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
                "down, rain stopped work, a worker was hurt, a leak). Not for work done. Pass the "
                "day when it is not today (date), the hours lost as minutes when they say how long "
                "(delay_duration_minutes) and the severity."
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
                            "SAFETY",
                            "QUALITY",
                            "OTHER",
                        ],
                        "description": (
                            "SAFETY: an accident, injury or someone fell (severity HIGH or CRITICAL). "
                            "QUALITY: a leak, seepage or crack."
                        ),
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
            name=REQUEST_MATERIAL,
            description=(
                "Material to be ordered or sent to the site ('50 bag cement order cheyyanam', "
                "'order 100 bags cement', 'nale 20 rod steel venam', 'need 2 loads sand by Monday'). "
                "It shows a 'Material request' card and is sent to their engineer when they tap Send. "
                "Never report_issue for an order: an issue is only material that ran out and held "
                "work up. Not for material that arrived or was used (save_material_receipt / usage)."
            ),
            parameters=_obj(
                {
                    "material": {"type": "string", "description": "The material, as they said it."},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "needed_by": {
                        "type": "string",
                        "description": "When it is needed, in their words ('tomorrow', 'Monday'), if said.",
                    },
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["material"],
            ),
        ),
        ToolSpec(
            name=NOTE_FOR_ENGINEER,
            description=(
                "Prepare a question for the user's engineer: it shows a 'Send to engineer' card and "
                "is sent only when they tap Send. ONLY when the user asks for it "
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
            name=SET_SITE_CONDITIONS,
            description=(
                "Set the day's site conditions or tomorrow's plan: the weather today (rain, sunny, "
                "cloudy, windy, extreme heat), whether the site worked a full day, half a day or not "
                "at all, and 'tomorrow plan: ...'. It shows a card; nothing is kept until they tap "
                "Save. 'Rain since 2 pm, work stopped 2 hours' is this tool AND report_issue (WEATHER, "
                "with the hours). A plan for tomorrow is ALWAYS this tool, never just noted."
            ),
            parameters=_obj(
                {
                    "weather": {
                        "type": "string",
                        "enum": ["sunny", "cloudy", "rainy", "windy", "extreme_heat"],
                        "description": "Only if the weather is said.",
                    },
                    "site_working": {
                        "type": "string",
                        "enum": ["full", "half", "none"],
                        "description": "full day / half day / no work, only if said.",
                    },
                    "hours_lost": {
                        "type": "number",
                        "description": "Hours of work lost today, only if said as hours.",
                    },
                    "tomorrow_plan": {
                        "type": "string",
                        "description": "Tomorrow's plan in their words ('2nd floor slab casting, need 15 workers').",
                    },
                    "date": _DATE,
                    "project": _PROJECT,
                    "site": _SITE,
                }
            ),
        ),
        ToolSpec(
            name=SET_UNIT_CONVERSION,
            description=(
                "Remember, for the whole company, how a unit of a material compares with its stock "
                "unit. ONLY after a save tool answered that the material is counted in another unit "
                "and the user then gave the numbers; never ask about units yourself, save first. "
                "Copy the numbers as they said them: '1 is 300' -> unit_amount 1, stock_amount 300; "
                "'28 make 1' -> unit_amount 28, stock_amount 1. Then save their entry again with "
                "their own amount and unit."
            ),
            parameters=_obj(
                {
                    "material": {"type": "string"},
                    "unit": {"type": "string", "description": "The unit they reported in."},
                    "unit_amount": {
                        "type": "number",
                        "description": "How many of that unit, as they said it (usually 1).",
                    },
                    "stock_amount": {
                        "type": "number",
                        "description": "How much of the stock unit that many make, as they said it.",
                    },
                },
                ["material", "unit", "unit_amount", "stock_amount"],
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
                "Undo ('undo', 'undo that', 'delete that', 'remove the painters', 'cancel the last "
                "expense'). By default it removes the entries of the user's latest card, which "
                "the context lists with an id in brackets. When they mean only some of them, "
                "pass those ids as targets; never invent an id. With several entries on the card "
                "and no targets, the user is asked which one."
            ),
            parameters=_obj(
                {
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ids from the context's latest saved card, only when they name some of its entries.",
                    },
                    "what": {
                        "type": "string",
                        "enum": ["latest_update", "expense", "transfer", "petty_cash"],
                        "description": "Omit for the latest card; expense, transfer or petty_cash for a money entry.",
                    },
                }
            ),
        ),
        ToolSpec(
            name=CHANGE_OR_UNDO,
            description=(
                "Undo or change something THEY ALREADY SAVED ('undo', 'undo that', 'remove the cement', "
                "'last expense venda', 'alla, 5 mason aanu'). The system asks them to confirm a removal "
                "with a card first; nothing is removed before they tap Yes. 'last' is their latest Save; "
                "otherwise pass the id the context gives, or a few words of what they mean ('cement', "
                "'diesel expense'). To correct a figure of a saved entry pass changes (named as the "
                "entry's own save tool names them). Not for a card they have not saved yet "
                "(update_pending_card / Cancel)."
            ),
            parameters=_obj(
                {
                    "target": {
                        "type": "string",
                        "description": "'last', an id from the context, or a few words describing the saved entry.",
                    },
                    "changes": _CHANGES,
                },
                ["target"],
            ),
        ),
        ToolSpec(
            name=UPDATE_PENDING_CARD,
            description=(
                "Change one item of the user's OPEN card (the one with Save / Cancel not tapped "
                "yet): 'alla, 8 mason aanu', '30 bag alla 20', 'helper 10 aanu'. Pass the card id "
                "and the item's number from the context, and only the fields that change, "
                "named as the item's own save tool names them. A card they already saved is not "
                "changed this way, unless the context gives that saved card's id for it (then a "
                "Change card is shown for them to save)."
            ),
            parameters=_obj(
                {
                    "card_id": {"type": "string", "description": "The open card's id, from the context."},
                    "item_index": {"type": "integer", "description": "The item's number on that card, from 1."},
                    "changes": _CHANGES,
                },
                ["card_id", "item_index", "changes"],
            ),
        ),
        ToolSpec(
            name=ASK_USER,
            description=(
                "Ask the user ONE question when you cannot tell what they mean or something "
                "needed is missing, instead of guessing. When several things in their message "
                "miss a detail, ask for all of them in this one question ('How many holo bricks, "
                "and how many scaffolders and plasterers?'). Ends your turn; their answer comes "
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
                    "other_parts": {
                        "type": "array",
                        "description": (
                            "Every other part of their message that this question does not ask "
                            "about and that you are not saving this turn, so it is taken up next. "
                            "[] when there is none."
                        ),
                        "items": _LATER_ITEM,
                    },
                },
                ["question", "other_parts"],
            ),
        ),
        ToolSpec(
            name=STILL_TO_DO,
            description=(
                "Note the parts of their message you cannot record this turn (a question is "
                "waiting, or a detail is missing), so they are taken up next; or drop listed "
                "parts that are done or not needed. Never leave a part of their message out."
            ),
            parameters=_obj(
                {
                    "items": {"type": "array", "items": _LATER_ITEM},
                    "drop": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Numbers of listed 'still to do' parts that are already recorded or "
                            "that they say are not needed."
                        ),
                    },
                },
            ),
        ),
        ToolSpec(
            name=QUERY_LABOUR,
            description=(
                "Answer 'how many workers / who worked / labour cost' from saved records. "
                "Leave trade out unless the question names one: a headcount counts every trade. "
                "Asked about another day ('yesterday?', 'last week?'), pass date or date_range."
            ),
            parameters=_obj(
                {
                    "date": _DATE,
                    "date_range": _PERIOD,
                    "trade": {"type": "string"},
                    "as_pdf": _AS_PDF,
                    "send_as": _SEND_AS,
                    "project": _PROJECT,
                    "site": _SITE,
                }
            ),
        ),
        ToolSpec(
            name=QUERY_MATERIALS,
            description=(
                "How much of a material is in stock now (all materials if none named). Asked how "
                "much was used or received on a day or in a period ('cement used today?', 'received "
                "yesterday?', 'this week?'), pass date or date_range: the answer then gives that "
                "period's received and used from the records, with the stock now."
            ),
            parameters=_obj(
                {
                    "material": {"type": "string"},
                    "date": _DATE,
                    "date_range": _PERIOD,
                    "asking": {
                        "type": "string",
                        "enum": ["used", "received"],
                        "description": (
                            "Which side the question is about: 'used' for 'cement used yesterday?', "
                            "'received' for 'what came in today?'. Omit for stock or both."
                        ),
                    },
                    "as_pdf": _AS_PDF,
                    "send_as": _SEND_AS,
                    "project": _PROJECT,
                    "site": _SITE,
                }
            ),
        ),
        ToolSpec(
            name=QUERY_WORK_LOG,
            description=(
                "Answer what was logged / open site issues (the site log). Asked about a day "
                "('what was done yesterday?'), pass date or date_range."
            ),
            parameters=_obj(
                {
                    "date": _DATE,
                    "date_range": _PERIOD,
                    "work_type": {"type": "string"},
                    "as_pdf": _AS_PDF,
                    "send_as": _SEND_AS,
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
                    "as_pdf": _AS_PDF,
                    "send_as": _SEND_AS,
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
            name=SET_REPLY_LANGUAGE,
            description=(
                "The user asks you to ALWAYS reply in one language, whatever they type in "
                "('reply in Malayalam', 'eppozhum Malayalathil reply cheyyu', 'I type Manglish, "
                "answer in Malayalam script', 'English il reply cheyyu'). Kept until they change it. "
                "'auto' (or 'reply in my language') goes back to answering in the language of each "
                "message. Not for a one-off translation."
            ),
            parameters=_obj(
                {
                    "language": {
                        "type": "string",
                        "enum": ["english", "manglish", "malayalam", "hindi", "hinglish", "auto"],
                        "description": (
                            "manglish = Malayalam in English letters; malayalam = Malayalam script; "
                            "hinglish = Hindi in English letters."
                        ),
                    }
                },
                ["language"],
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
            name=ADD_MEMBER,
            description=(
                "Add a person to a project's team, only when an admin or project manager asks "
                "(add / include / put X in the project). The user confirms with Yes."
            ),
            parameters=_obj(
                {
                    "name": {"type": "string", "description": "The person's name, as they said it."},
                    "role": {
                        "type": "string",
                        "description": "Their role if said: supervisor, site engineer, project manager ...",
                    },
                    "phone": {"type": "string", "description": "Their WhatsApp number, only if given."},
                    "new_person": {
                        "type": "boolean",
                        "description": "Only true after the user said yes to adding them as a new person.",
                    },
                    "project": _PROJECT,
                },
                ["name"],
            ),
        ),
        ToolSpec(
            name=GET_JOIN_CODE,
            description=(
                "Send the company's join code and a message to forward to the team, when an admin "
                "or project manager asks for it in any words ('code entha?', 'how do people "
                "join?', 'invite link', 'how do I add my team?'). Not for adding one named "
                "person (add_member). The system sends the code itself; do not repeat it."
            ),
            parameters=_obj({}),
        ),
        ToolSpec(
            name=CORRECT_WORK_QUANTITY,
            description=(
                "Change the quantity of the work just logged in this chat, when they say a "
                "number was wrong ('correction, it was 150 not 180', 'make that 30 sqm'). The "
                "user confirms with Yes. Not for a new entry."
            ),
            parameters=_obj(
                {
                    "new_quantity": {"type": "number"},
                    "unit": {"type": "string", "description": "Only if they restate the unit."},
                    "reason": {"type": "string", "description": "Only if they say why."},
                },
                ["new_quantity"],
            ),
        ),
        ToolSpec(
            name=UPDATE_ISSUE,
            description=(
                "Change a site issue reported earlier: it is fixed / sorted / done "
                "(resolve), seen and being handled (acknowledge), will not be fixed (wont_fix), "
                "was reported by mistake (cancel), or is back again (reopen). Resolving shows a "
                "'To close' card (Save / Cancel); the other actions ask Yes / No. For resolve, pass "
                "`about` with the words that name the issue ('crane') -- never pick one yourself: the "
                "system matches the words, or lists the open issues as buttons when it is unclear. "
                "'Both are fixed' / 'all done' is all_issues true."
            ),
            parameters=_obj(
                {
                    "action": {
                        "type": "string",
                        "enum": ["resolve", "acknowledge", "wont_fix", "cancel", "reopen"],
                    },
                    "about": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "resolve only: the words naming the issue(s), e.g. ['crane'].",
                    },
                    "all_issues": {
                        "type": "boolean",
                        "description": "resolve only: true when they say all / both of the open issues are fixed.",
                    },
                    "all_matching": {
                        "type": "boolean",
                        "description": (
                            "resolve only: true when they say ALL the issues about that thing are fixed "
                            "('ellam mixer issues-um close cheyyu', 'all the crane problems')."
                        ),
                    },
                    "notes": {"type": "string", "description": "What was done, only if said."},
                    "project": _PROJECT,
                    "site": _SITE,
                },
                ["action"],
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
        """The one site ``name`` says, whole words only (V1 audit SIT-13); None
        when it matches none or several, so the sender is asked."""
        from types import SimpleNamespace

        from .site_match import find_sites

        rows = [SimpleNamespace(id=sid, name=sname, project_id=pid) for sid, sname, pid in self.sites if project_id in (None, pid)]
        hits = find_sites(rows, name, {pid: pname for pid, pname in self.projects})
        return str(hits[0].id) if len(hits) == 1 else None


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


def _output_format(args: dict[str, Any]) -> dict[str, str]:
    """``send_as`` "pdf" or "image" becomes the workflow's ``output_format``;
    the old ``as_pdf=true`` still means pdf. Text (the default) sets nothing."""
    send_as = args.get("send_as")
    if send_as in ("pdf", "image"):
        return {"output_format": send_as}
    return {"output_format": "pdf"} if args.get("as_pdf") is True else {}


#: The day words a model may pass through unchanged from the user's own
#: language; the pipeline reads English ones and ISO dates only (request 88:
#: "innale report ayakku" was refused while "yesterday's report" was sent).
_DAY_WORDS = {
    "innale": "yesterday",
    "innalathe": "yesterday",
    "innalethe": "yesterday",
    "ഇന്നലെ": "yesterday",
    "ഇന്നലത്തെ": "yesterday",
    "innu": "today",
    "ഇന്ന്": "today",
}


def day_argument(value: Any) -> Any:
    """The tool's ``date`` argument with a day word in the sender's language
    ("innale", "innaleത്തെ") turned into the word the pipeline reads."""
    text = str(value or "").strip().casefold()
    if not text:
        return value
    if text in _DAY_WORDS:
        return _DAY_WORDS[text]
    prefix = re.match(r"[a-z]+", text)
    if prefix and prefix.group(0) in _DAY_WORDS and prefix.group(0) != text:
        return _DAY_WORDS[prefix.group(0)]
    return value


def to_candidate(name: str, args: dict[str, Any], scope: ScopeLookup) -> Candidate | None:
    """The understanding a tool call stands for, or None for a tool that is not
    a workflow (ask_user, undo_last)."""
    sc = _scope(args, scope)
    date = day_argument(args.get("date"))
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
    if name == TRANSFER_MATERIAL:
        fields = {
            "material_name": args.get("material"),
            "quantity": args.get("quantity"),
            "unit": args.get("unit"),
            "direction": "transfer",
            "to_site_name": str(args.get("to_site") or "").strip(),
            "occurred_on": date,
            "new_material": None,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.MATERIAL_UPDATE, fields=_clean(fields))
    if name == SAVE_OPENING_STOCK:
        fields = {
            "material_name": args.get("material"),
            "quantity": args.get("quantity"),
            "unit": args.get("unit"),
            "direction": "opening_stock",
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
        # Not an issue: a card whose Send tap messages the engineer (actions.py).
        fields = {"_action": "engineer_question", "question": question, **sc}
        return Candidate(semantic_type=SemanticType.SITE_ISSUE, fields=_clean(fields))
    if name == REQUEST_MATERIAL:
        if not str(args.get("material") or "").strip():
            return None
        # Not an issue (request 143): a card whose Send tap messages the engineer (actions.py).
        fields = {
            "_action": "material_request",
            "material": str(args.get("material") or "").strip(),
            "quantity": args.get("quantity"),
            "unit": args.get("unit"),
            "needed_by": args.get("needed_by"),
            **sc,
        }
        return Candidate(semantic_type=SemanticType.SITE_ISSUE, fields=_clean(fields))
    if name == SET_SITE_CONDITIONS:
        fields = {
            "_action": "site_conditions",
            "weather": args.get("weather"),
            "site_working": args.get("site_working"),
            "hours_lost": args.get("hours_lost"),
            "tomorrow_plan": args.get("tomorrow_plan"),
            "occurred_on": date,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.GENERAL_SITE_UPDATE, fields=_clean(fields))
    if name == TRANSFER_MONEY:
        fields = {
            "amount": args.get("amount"),
            "from_account_name": args.get("from_account"),
            "to_account_name": args.get("to_account"),
            "description": args.get("description"),
        }
        return Candidate(semantic_type=SemanticType.TRANSFER, fields=_clean(fields))
    if name == QUERY_LABOUR:
        fields = {
            "date": date,
            "date_range": args.get("date_range"),
            "trade": args.get("trade"),
            **_output_format(args),
            **sc,
        }
        return Candidate(semantic_type=SemanticType.LABOUR_QUERY, fields=_clean(fields))
    if name == QUERY_MATERIALS:
        fields = {
            "material_name": args.get("material"),
            "date": date,
            "date_range": args.get("date_range"),
            "asking": args.get("asking") if args.get("asking") in ("used", "received") else None,
            **_output_format(args),
            **sc,
        }
        return Candidate(semantic_type=SemanticType.INVENTORY_QUERY, fields=_clean(fields))
    if name == QUERY_WORK_LOG:
        fields = {
            "date": date,
            "date_range": args.get("date_range"),
            "work_type": args.get("work_type"),
            **_output_format(args),
            **sc,
        }
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
            **_output_format(args),
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
    if name == ADD_MEMBER:
        fields = {
            "member_name": str(args.get("name") or "").strip(),
            "role": args.get("role"),
            "whatsapp_number": args.get("phone"),
            "new_person": True if args.get("new_person") is True else None,
            **sc,
        }
        return Candidate(semantic_type=SemanticType.ADD_PROJECT_MEMBER, fields=_clean(fields))
    if name == CORRECT_WORK_QUANTITY:
        fields = {"new_quantity": args.get("new_quantity"), "unit": args.get("unit"), "reason": args.get("reason")}
        return Candidate(semantic_type=SemanticType.ACTIVITY_CORRECTION, fields=_clean(fields))
    if name == UPDATE_ISSUE:
        if str(args.get("action") or "") == "resolve":
            # Request 104, C: a card ("To close: ...") naming the issue by the
            # sender's words, several at once; the Save tap closes them.
            about = args.get("about")
            fields = {
                "_action": "close_issues",
                "about": [str(a) for a in about] if isinstance(about, list) else about,
                "all_issues": args.get("all_issues") is True,
                "all_matching": args.get("all_matching") is True,
                **sc,
            }
            return Candidate(semantic_type=SemanticType.SITE_ISSUE_UPDATE, fields=_clean(fields))
        fields = {"action": args.get("action"), "resolution_notes": args.get("notes"), **sc}
        return Candidate(semantic_type=SemanticType.SITE_ISSUE_UPDATE, fields=_clean(fields))
    if name == CREATE_PROJECT:
        fields = {"name": str(args.get("name") or "").strip(), "location": args.get("location")}
        return Candidate(semantic_type=SemanticType.PROJECT_CREATE, fields=_clean(fields))
    if name == UNDO_LAST:
        what = str(args.get("what") or "latest_update")
        if what == "latest_update":
            return None
        return Candidate(semantic_type=SemanticType.REVERSAL, fields={"target_kind": what})
    return None
