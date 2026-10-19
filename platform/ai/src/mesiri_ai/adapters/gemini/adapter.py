"""Gemini vision + structured-extraction adapter (M3).

Implements :class:`VisionUnderstandingProvider` and
:class:`StructuredExtractionProvider`. The ``google-genai`` SDK is imported
lazily and isolated here; responses are parsed into Mesiri-owned models, and a
non-JSON / unparseable response is mapped to PROVIDER_MALFORMED_OUTPUT.

NOTE: exact SDK call/field names are assumed and must be verified against the
installed ``google-genai`` version (tracked in the integration report). Tests
use the fake provider.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ... import usage
from ...core.errors import malformed_output
from ...core.fallback import call_with_resilience
from ...models import (
    DecompositionResult,
    ExtractionResult,
    SpeechResult,
    TranslationResult,
    VisionResult,
    parse_extracted_intents,
)

_log = logging.getLogger("mesiri.ai.gemini")

_JPEG_QUALITY = 85

try:
    from mesiri.bootstrap.settings import GeminiSettings
except Exception:  # pragma: no cover
    GeminiSettings = Any  # type: ignore

_VISION_PROMPT = (
    "You are analysing a construction-site image. Return strict JSON with keys: "
    '"document_classification" (e.g. receipt, invoice, attendance_sheet, '
    "site_photo, unknown), "
    '"description" (short), and "fields" (object of any legible key/values). '
    "Never invent values; omit unknown keys.\n\n"
    "If the image is an attendance sheet, muster roll, labour register or any "
    "handwritten list of people who worked (classify it as attendance_sheet), "
    'then "fields" MUST contain a "workers" array with one entry per person or '
    "group listed, each with: "
    '"name" (as written -- omit for an unnamed group), '
    '"trade" (mason, helper, painter, carpenter, electrician, plumber, welder, '
    'bar bender, fitter, supervisor, operator, driver, ...), '
    '"headcount" (1 for a named person; the count for a group row), '
    '"daily_wage" (plain number, only if a rate is written). '
    "Transcribe EVERY row, in the order written. Do not summarise, do not total, "
    "and do not drop rows you are unsure of -- transcribe the name as best you "
    "can read it. If a row is marked absent, leave it out. If you genuinely "
    'cannot read a name, use "?" for that name rather than skipping the row, so '
    "the count stays right.\n\n"
    "Sheets are often written in Malayalam, Hindi, Tamil, Bengali or another "
    "Indian script. Handle the two kinds of text differently, because they are "
    "not the same problem:\n"
    '- NAMES: transliterate the sound into Latin script for "name" '
    '(രവി -> "Ravi", सुरेश -> "Suresh"). '
    "NEVER translate a name into an English word -- a name is a person, not "
    'vocabulary. Also return the original spelling unchanged in "name_original" '
    "so nothing is lost and the reading can be checked.\n"
    '- TRADES: translate into the English trade word for "trade" '
    '(കൊത്തുപണിക്കാരന് -> "mason", '
    'मजदूर -> "helper"), using the trade list above.\n'
    "Numerals in any script become plain digits.\n\n"
    "If the image is a supplier invoice, bill, cash memo or delivery challan "
    "for materials (classify it as invoice), then \"fields\" MUST contain a "
    '"line_items" array with one entry per material line, each with: '
    '"material_name" (as printed), '
    '"quantity" (plain number), '
    '"unit" (bags, kg, tons, cum, nos, ... as printed), '
    '"unit_cost" (rate per unit, only if a rate is printed), '
    '"line_total" (only if a line amount is printed). '
    'Also include "supplier_name", "invoice_number", "invoice_date" '
    '(YYYY-MM-DD) and "invoice_total" when they are legible.\n'
    "Transcribe EVERY material row, in the order printed. Do not summarise and "
    "do not total. Skip rows that are not materials (freight, loading charges, "
    "round-off, tax lines) -- those belong to the invoice total, not to stock.\n"
    "Do NOT extract GST/HSN codes, tax breakdowns, bank details, IFSC, vehicle "
    "or LR numbers, payment terms, or amount-in-words. They are not needed and "
    "guessing them wastes accuracy that the material lines need.\n"
    "Never compute a missing number. If a rate or an amount is not printed, "
    "omit that key -- a value that was never on the paper must not be invented."
)

_EXTRACTION_PROMPT = (
    "The text may be in any language (Malayalam, Hindi, Tamil, Bengali, English, "
    "or code-mixed) -- read it directly, do not wait for a translation. Extract "
    'structured construction data from the text. Return strict JSON with keys: '
    '"detected_language" (the source language\'s common English name, e.g. '
    '"Malayalam", "English"), '
    '"intents" (array -- one entry per DISTINCT request the message makes. '
    "The OVERWHELMING majority of messages state exactly ONE thing: return a "
    "single-entry array unless the text CLEARLY and explicitly asks for "
    "several separate, unrelated actions in the same breath -- e.g. \"create "
    "a project called Bidilaj, then a site called Site A, then add Usman as "
    "site engineer\" is three entries. A single report is ONE entry even "
    "when it touches more than one fact -- \"used 40 bags of cement for the "
    "foundation\" is one material_update entry (the foundation work is a "
    "field of that report, `work_item`, never a second intent); \"paid 5000 "
    "for cement\" is one expense entry, never split into an expense plus a "
    "material_update just because cement is mentioned. When genuinely "
    "unsure whether something is one request or two, prefer ONE -- a wrong "
    "split loses information the user has to notice and correct; treating "
    "two real requests as one still lets the first be understood correctly, "
    "so it is the safer mistake to make. "
    "Each entry in \"intents\" is an object with: "
    '"semantic_type" (expense|equipment_usage|material_update|material_invoice|labour_update|'
    "general_site_update|activity_correction|site_issue|site_issue_update|general_question|whoami_question|inventory_query|"
    "labour_query|activity_query|dpr_request|finance_query|transfer|petty_cash|reversal|"
    "account_admin|project_create|site_create|project_detail_query|"
    "automation_setup|add_project_member|create_user|unknown), "
    '"fields" (object, values in English except proper nouns/names -- see '
    "per-type rules below for how to handle names), "
    '"missing_fields" (array), '
    '"field_confidences" (object of field->0..1). '
    "Never invent values. quantity is always a plain number: strip approximation "
    'words like "almost", "about", "around", "roughly", "nearly" and extract the '
    'number stated (e.g. "almost 70 bags" -> quantity 70).\n\n'
    "Field schema per semantic_type (only include keys you actually found):\n"
    "Note: For ALL semantic types, if the text mentions a specific project, site, or location by name (e.g. 'project alpha', 'at the main site'), extract it as 'project_name'.\n"
    "Note: For expense, material_update and labour_update, occurred_on is the day the "
    "event happened, ONLY when the message says so: either \"yesterday\" / \"today\" / "
    "\"day before yesterday\" verbatim, or an exact ISO date \"YYYY-MM-DD\" when a full "
    "date is written (e.g. \"on 25 July\" -> \"2026-07-25\"). Omit occurred_on entirely "
    "when no day is mentioned -- never guess it, and never emit a bare weekday like "
    "\"Friday\", which is ambiguous.\n"
    "- expense: amount, currency, vendor, category, description, paid_to, occurred_on, "
    "project_name, tax_rate, tax_amount, is_tax_inclusive. tax_rate/tax_amount are only "
    "for a bill/receipt that itemizes a specific tax line (e.g. \"GST 18%\", \"CGST 9% + "
    "SGST 9%\" -- sum the parts into one tax_rate/tax_amount, \"VAT: ₹180\") -- omit both "
    "entirely if no tax is itemized, never guess or estimate a rate/amount that isn't "
    "explicitly stated. tax_rate is the plain percentage number (18, not \"18%\"); "
    "tax_amount is the plain currency amount. is_tax_inclusive is `true` when amount "
    "already includes the tax (the common case for a total-due figure) or `false` when "
    "tax is added on top of amount -- infer from context (a receipt's grand total is "
    "inclusive; a quote/invoice listing \"subtotal + tax = total\" separately means "
    "amount is the subtotal, exclusive) and omit entirely if genuinely unclear.\n"
    "- equipment_usage: equipment_name, duration_hours, operator, activity, project_name\n"
    "- material_update: material_name, quantity, unit, direction, work_item, supplier, "
    "project_name, occurred_on. "
    'supplier is who the material came from when the sender says so ("40 bags cement from '
    'Sharma Traders" -> "Sharma Traders"); omit it otherwise. '
    'direction MUST be exactly "received" or "used" -- never any other word. '
    'Use "received" when material arrived, was delivered, or was brought to site '
    '(e.g. "50 bags of cement arrived", "cement delivered today"). '
    'Use "used" when material was consumed, used, or applied to work '
    '(e.g. "20 bags of cement used for the foundation"). '
    'If no direction is explicitly stated (e.g. "record 50 bags of cement"), default to "used". '
    "work_item is only for used material: the activity or task it was used for "
    '(e.g. "slabing the footing area", "column casting"). Omit work_item entirely '
    "for received material.\n"
    "- material_invoice: supplier_name, invoice_number, invoice_date, "
    "invoice_total, line_items (array), project_name. Use this type ONLY when "
    "the input is a supplier invoice, bill, cash memo or delivery challan "
    "listing materials with quantities -- a document, not a sentence. "
    'One person saying "50 bags of cement arrived" is material_update; a '
    "printed document listing several materials is material_invoice. "
    "Each line_items entry has: material_name, quantity, unit, and "
    "unit_cost/line_total when a price is printed. Copy the array through "
    "unchanged if it is already present in the input -- do not re-derive, "
    "re-order or total it. Never invent a price that was not printed, and "
    "never extract GST/HSN, tax breakdowns, bank details or payment terms.\n"
    "- labour_update: workers (array), contractor, hours, project_name, occurred_on. "
    "Each item in workers is ONE line of the attendance report, with keys: "
    '"name" (the person\'s name -- omit entirely for an unnamed group), '
    '"trade" (mason, helper, painter, carpenter, electrician, plumber, welder, '
    'bar bender, fitter, supervisor, operator, driver, ...), '
    '"headcount" (how many people this line covers -- always 1 for a named '
    'person), "daily_wage" (plain number, only when stated), '
    '"attendance_status" (one of "present", "absent", "half_day"), '
    '"overtime_hours" (plain number, only from an explicit OT column or '
    '"2 hours overtime"), "contractor" (this line\'s own contractor/agency, '
    'when the sheet gives different ones per worker), "remarks" (the sheet\'s '
    'free-text note for this person, verbatim), "activity" (the work item '
    'this line worked on, when stated). '
    "attendance_status: a printed muster roll marks each person P / A / H (or "
    "Present / Absent / Half day, or a tick vs a cross). Map P/tick/present -> "
    '"present", A/cross/absent/leave -> "absent", H/HD/half -> "half_day". '
    "A typed message that simply names who worked is ALL present -- omit the "
    "key entirely rather than writing it on every line. Only emit it when the "
    "source actually distinguishes, which in practice means a photographed "
    "sheet. NEVER mark someone absent because their row is blank or "
    "unreadable: omit the line instead, since a blank cell and a cross mean "
    "different things and guessing wrong deletes a day's pay. "
    "Sites report named workers and plain headcounts interchangeably, often in "
    'the same message. "Ravi mason, Arun painter, 12 helpers, 4 carpenters" -> '
    'workers: [{"name":"Ravi","trade":"mason","headcount":1}, '
    '{"name":"Arun","trade":"painter","headcount":1}, '
    '{"trade":"helper","headcount":12}, {"trade":"carpenter","headcount":4}]. '
    "NEVER invent a name: if the text only says \"12 helpers\", omit \"name\" for "
    "that line. NEVER merge two named people into one line, and never collapse a "
    "named person into a count. A message with no names at all is still valid -- "
    'emit one workers entry per trade mentioned. "20 workers today" (no trade) '
    '-> workers: [{"headcount":20}]. '
    "If a name is written in a non-Latin script, transliterate the sound into "
    'Latin for "name" (രവി -> "Ravi") and keep the original spelling in '
    '"name_original" -- never translate a name into an English word. Translate '
    "trades into the English trade word.\n"
    "- general_site_update: narrative, work_type, quantities (array), location, "
    "contractor, project_name, occurred_on, update_kind. "
    "narrative is the report in the sender's own words. work_type is the single "
    'primary kind of work if one is clear (e.g. "plastering", "concreting", '
    '"blockwork") -- omit if the message describes several unrelated things or '
    "names none specifically. quantities is an array of every measured amount "
    'stated, each an object with "work_type" (may repeat the top-level work_type, '
    'or differ for a different item in the same message), "quantity" (a plain '
    'number) and "unit" (e.g. "sqm", "m3", "bags", "nos", "m") -- omit quantities '
    "entirely for a narrative-only report with nothing measured "
    '(e.g. "started plastering on 2nd floor" has no quantities; "180 sqm '
    'plastering done" -> quantities: [{"work_type":"plastering","quantity":180,'
    '"unit":"sqm"}]). location is the free-text place on site the work happened '
    '(e.g. "Block A", "2nd floor", "km 12+400") -- omit if unstated, never invent '
    "one. contractor is the name of a contractor/agency mentioned, if any. "
    "update_kind classifies whether this describes brand-new work or an update "
    "to something already reported earlier in the day, and MUST be exactly one "
    'of "started", "progress", "paused", "resumed", "completed", or omitted '
    'entirely when genuinely unclear. Use "started" only when the message '
    'explicitly begins new work (e.g. "started plastering on 2nd floor"). Use '
    '"progress" for a further update to work already underway with no explicit '
    'stop (e.g. "completed another 40 sqm", "50 sqm done so far" as a running '
    'total). Use "completed" only when the message says the work is now fully '
    'finished (e.g. "finished plastering", "plastering done"). Use "paused" for '
    'a stoppage without finishing (e.g. "stopped for rain", "paused for lunch"). '
    'Use "resumed" for explicitly restarting paused work. Omit update_kind '
    "entirely -- never guess -- when the message could equally be new work or a "
    "continuation; a plain quantity update with no other context "
    '(e.g. just "180 sqm") should still get "progress" since a bare number is '
    "never how new work is first reported. This type is for reporting work done "
    "or in progress -- never for problems, delays, or blockers (those are "
    "site_issue, a different report type).\n"
    "- activity_correction: new_quantity, unit, work_type. Use this type ONLY "
    "when the sender is correcting a number they (or someone) already "
    'reported this conversation -- explicit correction language: "make '
    'that X", "actually it was X", "correct that to X", "sorry, it\'s X '
    'not Y", "should be X, not Y", "I meant X". new_quantity is the '
    "corrected number (the right one, not the wrong one being replaced); "
    "unit is its unit if stated. work_type is only for when the message "
    'itself names which work the correction is about (e.g. "the plastering '
    'was actually 180, not 80") -- omit if it just restates a number with '
    'no work named. NEVER use this type for a plain new measurement '
    '("another 40 sqm done", "180 sqm so far", "completed 50 more") -- '
    "those are general_site_update with update_kind=progress, reporting "
    "genuinely new work, not fixing a mistake. The distinguishing signal is "
    "always explicit correction language, never the number alone.\n"
    "- site_issue: issue_type, severity, narrative, delay_duration_minutes, project_name, "
    'occurred_on. issue_type MUST be exactly one of "WEATHER", "MATERIAL_SHORTAGE", '
    '"LABOUR_SHORTAGE", "DRAWING_PENDING", "EQUIPMENT_BREAKDOWN", "INSPECTION_WAITING", '
    '"ACCESS", "OTHER" -- infer from context (e.g. "no cement left" -> MATERIAL_SHORTAGE, '
    '"JCB broke down" -> EQUIPMENT_BREAKDOWN, "raining since morning" -> WEATHER, '
    '"waiting on the structural drawings" -> DRAWING_PENDING, "site is locked, no one can '
    'get in" -> ACCESS, "waiting for the inspector to sign off" -> INSPECTION_WAITING), '
    'defaulting to "OTHER" only when genuinely unclear which bucket it falls in. severity '
    'MUST be exactly one of "LOW", "MEDIUM", "HIGH", "CRITICAL" -- infer from the language '
    'used (e.g. "completely stopped", "urgent", "everyone is idle" -> HIGH/CRITICAL; a '
    'minor inconvenience -> LOW/MEDIUM), defaulting to "MEDIUM" when unclear. narrative is '
    "the blocker description in the sender's own words. delay_duration_minutes is a plain "
    "number of minutes only when the message states how long work has been stopped/delayed "
    "(e.g. \"stopped for 2 hours\" -> 120) -- omit if not stated. This type is specifically "
    "for a NEW problem, delay, or blocker that stops or slows down work -- never for a plain "
    "progress report (general_site_update) and never for a QUESTION about existing issues "
    '("any open issues?" is activity_query, asking; "ran out of cement, work stopped" is '
    "site_issue, reporting).\n"
    "- site_issue_update: action, resolution_notes. Use this type when the user wants to "
    "acknowledge, resolve, mark won't-fix, withdraw, or reopen their most recently "
    'reported site issue (e.g. "acknowledge that issue", "that\'s fixed now, mark it '
    'resolved", "we can\'t fix that, mark it as won\'t fix", "close that blocker"). '
    'action MUST be exactly "acknowledge", "resolve", "wont_fix", "cancel", or "reopen" '
    "-- never any other word; infer it from what the user says. Use \"cancel\" when the "
    "user says the issue should never have been reported at all -- a mistake, the wrong "
    'site, or a false alarm (e.g. "ignore that issue, wrong site", "cancel that, I was '
    'wrong", "that was a mistake, remove it"). Use "reopen" when the user says a '
    'previously closed issue is not actually settled (e.g. "that\'s not fixed, reopen '
    'it", "the leak is back", "we closed that too early"). Do NOT use "cancel" for a '
    'problem that was real and then went away -- that is "resolve". '
    "resolution_notes is optional freeform text explaining how it was "
    'resolved, why it won\'t be fixed, why it was withdrawn, or why it is being '
    'reopened (e.g. "pump replaced", "not worth fixing, site '
    'closing next week") -- omit if not stated. This ALWAYS targets the single most '
    "recently reported issue in the right status -- never extract an issue type, "
    "severity, or narrative to identify which one; that resolution happens elsewhere. "
    "Never confuse with site_issue (which reports a brand NEW problem).\n"
    "- general_question: question, topic\n"
    "- whoami_question: question\n"
    "- inventory_query: material_name, output_format, project_name (omit material_name if "
    'asking about all materials, e.g. "show inventory"). Use this type for questions about how '
    'much of a material is currently in stock (e.g. "how much cement is left?", '
    '"current stock of steel") or its movement history '
    '(e.g. "show today\'s cement history"). This is a question, never an update. '
    'output_format is "pdf" ONLY when the user explicitly asks for the answer as a file/'
    'document (e.g. "send me the stock levels as pdf", "pdf of current inventory") -- omit '
    "entirely for a plain question that expects a normal chat reply.\n"
    "- labour_query: date_range, trade, output_format, project_name. Use this type for QUESTIONS "
    'about who worked and what labour cost (e.g. "how many workers today?", '
    '"who worked yesterday?", "labour cost this week", "how many masons on site?"). '
    "date_range is exactly one of \"today\", \"this_week\", \"this_month\" if a period "
    "is stated or implied; omit if none is. trade narrows to one trade when asked "
    '(e.g. "how many masons today" -> trade "mason"); omit for all trades. '
    'output_format is "pdf" ONLY when the user explicitly asks for the answer as a file/'
    'document (e.g. "send me the attendance list as pdf", "export today\'s labour as pdf") -- '
    "omit entirely for a plain question that expects a normal chat reply. "
    "CRITICAL: this is a question ABOUT existing records, never a new attendance "
    'report. "14 workers today" is a labour_update (recording who worked); '
    '"how many workers today?" is a labour_query (asking). Getting this backwards '
    "would record workers instead of counting them.\n"
    "- activity_query: date_range, project_name, work_type, output_format. Use this type for "
    'QUESTIONS about progress already logged or open site issues (e.g. "what did I log today?", '
    '"what happened on site X yesterday?", "show today\'s site log", "any open issues?", '
    '"what\'s blocking us on site Y?"). date_range is exactly one of "today", "this_week", '
    '"this_month" if a period is stated or implied; omit if none is. work_type narrows to '
    'one kind of work when asked (e.g. "any plastering logged today?" -> work_type '
    '"plastering"); omit for everything. output_format is "pdf" ONLY when the user explicitly '
    'asks for the answer as a file/document (e.g. "send me today\'s site log as pdf", "pdf of '
    'open issues") -- omit entirely for a plain question that expects a normal chat reply. '
    "CRITICAL: this is a question ABOUT existing "
    'progress/issue records, never a new report. "180 sqm plastering done" is a '
    'general_site_update (recording work); "what did I log today?" is an activity_query '
    "(asking). Getting this backwards would try to record a report instead of answering "
    "a question.\n"
    "- dpr_request: (no fields). Use this type ONLY when the user explicitly asks to be "
    'SENT today\'s Daily Progress Report / DPR as a document (e.g. "send me today\'s DPR", '
    '"share today\'s report", "send the daily report"). Distinct from activity_query, which '
    'asks a QUESTION about the log ("what did I log today?") and gets a text answer -- '
    "dpr_request wants the actual generated PDF document sent to them. Never use this for a "
    "vague \"how's the site doing\" question -- that is activity_query or general_question.\n"
    "- finance_query: query_kind, account_name, category_name, date_range, missing_receipts, "
    "output_format, project_name. "
    'query_kind MUST be exactly "balance" or "expenses" -- never any other word. '
    'Use "balance" for questions about how much money/cash is in an account '
    '(e.g. "how much cash do I have?", "balance of Site Cash", "how much money is left?"). '
    'account_name is the specific account asked about, if any (omit if asking about all '
    'accounts, e.g. "how much cash do I have"). '
    'Use "expenses" for questions about past spending '
    '(e.g. "show my expenses today", "how much did we spend on diesel?", '
    '"what did we spend this week?"). category_name is the expense category asked about, '
    'if any (e.g. "diesel", "fuel") -- omit if asking about all expenses. date_range is '
    'exactly one of "today", "this_week", "this_month" if a time period is stated or implied; '
    "omit if no time period is mentioned. missing_receipts is `true` when query_kind is "
    '"expenses" and the question is specifically about which expenses have no receipt/bill '
    'attached (e.g. "which expenses are missing receipts?", "show expenses without a bill", '
    '"who hasn\'t uploaded a receipt yet") -- omit entirely otherwise, never set it to false. '
    'output_format is "pdf" ONLY when the user explicitly asks for the answer as a file/'
    'document (e.g. "send me my balance as pdf", "export my expenses as pdf", "pdf of '
    'today\'s expenses", "can I get that as a document") -- omit entirely for a plain '
    "question that expects a normal chat reply. "
    "This is always a question, never an update -- "
    "never confuse with expense (which records a NEW expense being reported).\n"
    "- transfer: amount, from_account_name, to_account_name, description, project_name. "
    "Use this type for moving money between two of the organization's own accounts "
    '(e.g. "transfer ₹50,000 from Company Account to Site Cash", "move 10000 from '
    'the bank to petty cash"). from_account_name/to_account_name are the account '
    "names as stated -- extract them even if you're not sure they're real account "
    "names, they will be matched against the organization's actual accounts "
    "afterwards. Omit either name if not stated (the user will be asked to clarify). "
    "Never confuse with expense (paying someone/something outside the organization) "
    "or finance_query (a question, not a movement of money).\n"
    "- petty_cash: amount, recipient_name, direction, description, project_name. "
    "Use this type when money is given to or returned by a specific PERSON "
    '(not one of the organization\'s own accounts) as petty cash/advance '
    '(e.g. "give ₹20,000 petty cash to Alan", "issue 5000 cash advance to '
    'Priya", "Alan returns ₹3,000 petty cash", "Priya returned the remaining '
    '2000"). recipient_name is the person\'s name as stated -- extract it '
    "even if you're not sure it's a real user, it will be matched against "
    'the organization\'s users afterwards. direction MUST be exactly "issue" '
    '(money going out to the person) or "return" (money coming back from '
    'the person) -- never any other word. Never confuse with transfer '
    "(which moves money between the organization's own accounts, not to/from "
    "a person) or expense (paying an outside vendor/bill, not handing cash "
    "to a colleague).\n"
    "- reversal: target_kind. Use this type when the user wants to undo, "
    "reverse, cancel, or void their most recently recorded expense, "
    "transfer, petty cash movement, or site activity/progress report "
    '(e.g. "reverse my last expense", "cancel that transfer", '
    '"undo the diesel expense I just added", "void my last transaction", '
    '"delete that site update", "undo my last activity report", '
    '"remove the update I just sent", "reverse the petty cash I gave Alan", '
    '"cancel that advance"). '
    'target_kind MUST be exactly "expense", "transfer", "petty_cash", '
    '"attendance", or "activity" -- '
    "never any other word; infer it from what the user refers to -- "
    '"site update"/"activity"/"progress report"/"the work I just logged" '
    'means "activity"; "petty cash"/"advance"/"the cash I gave <person>" '
    'means "petty_cash"; "attendance"/"the workers I marked"/"today\'s '
    'labour"/"the headcount I sent" means "attendance" (e.g. "cancel that '
    'attendance, wrong site", "scrap the labour report I just sent"); '
    'defaulting to "expense" if genuinely ambiguous '
    "between expense and transfer, since that is the more common case. This "
    "always targets the single most recent record of that kind -- never "
    "extract an amount, date, or description for it.\n"
    "- account_admin: action, name, target_name, new_name, account_type. "
    "Use this type when the user wants to manage the organization's own "
    "money accounts themselves (create a new account, rename one, or "
    "deactivate one) -- never a specific transaction against one. action "
    'MUST be exactly "create", "rename", or "deactivate" -- never any '
    'other word. For "create": name is the new account\'s name (e.g. '
    '"create a new account called Petrol Card" -> name "Petrol Card"); '
    'account_type is "cash" or "bank" if stated, otherwise omit. For '
    '"rename": target_name is the account\'s current name and new_name is '
    'what it should become (e.g. "rename Main HDFC Bank Account to Office '
    'Cash" -> target_name "Main HDFC Bank Account", new_name "Office '
    'Cash"; "change the name of the main HDFC account to Alan Cash" -> '
    'target_name "main HDFC account", new_name "Alan Cash"). For '
    '"deactivate": target_name is the account to deactivate (e.g. '
    '"deactivate Petrol Card" -> target_name "Petrol Card"). '
    "target_name/new_name/name are best-effort hints as stated -- extract "
    "them even if you're not sure they match a real account, they will be "
    "matched against the organization's actual accounts afterwards. Never "
    "confuse with transfer (moving money between accounts) or petty_cash "
    "(money to/from a person) -- this only ever changes an account record "
    "itself, never moves money.\n"
    "- project_create: name, location, client. Use this type when the user "
    "wants to create a brand new Project record itself (e.g. \"create a new "
    "project called Skyline Towers\", \"start a new project at Kochi for "
    "client ABC Builders\") -- never an activity, site issue, or expense "
    "logged at an existing project (those use their own semantic types "
    "above). name is the new project's name -- always extract it even if "
    "you're not sure how it will be used afterwards. location and client "
    "are optional hints, stated as-is.\n"
    "- site_create: name, location. Use this type when the user wants to "
    "create a brand new Site record under an EXISTING project (e.g. "
    "\"create a new site called Block A\", \"add a site for the Kochi "
    "yard\") -- never a project itself (that's project_create) and never "
    "an activity/issue/expense logged at an existing site. Which project "
    "the site belongs to is NOT extracted here -- omit it entirely even if "
    "a project name is mentioned elsewhere in the message; that is "
    "resolved separately. name is the new site's name -- always extract "
    "it. location is an optional hint, stated as-is.\n"
    "- project_detail_query: output_format. Use this type when the user asks "
    "for a full summary/status/details of a project or site itself (e.g. "
    "\"give me all details of Skyline Towers\", \"what's the status of "
    "Block A\", \"tell me everything about this site\") -- distinct from "
    "activity_query (a day's activity/issue log) and finance_query (just "
    "balance/expenses): this is the project/site RECORD itself plus its "
    "current operational snapshot. Unlike project_create/site_create, DO "
    "extract the named project/site here -- per the blanket rule above, put "
    "it in 'project_name'/'site_name' so it can be matched against the "
    "org's real projects/sites; a bare \"tell me about this project\" with "
    "no name mentioned is also valid and falls back to context. "
    "output_format is \"pdf\" only when the user explicitly asks for a "
    "file/document -- omit entirely for a plain question expecting a "
    "normal chat reply.\n"
    "- automation_setup: time_of_day, frequency, day_of_week, automation_action, "
    "audience, audience_names, audience_role, message. Use this type when the "
    "user wants to set up a recurring/standing RULE that fires later on its own "
    "schedule (e.g. \"every day at 5pm send me the DPR\", \"at 3 o'clock tell me "
    "who hasn't reported\", \"every Monday remind Ilan and Hysam to submit their "
    "report\") -- never a one-time question or report request answered right now "
    "(those are dpr_request/activity_query/project_detail_query/etc). "
    "time_of_day is the clock time converted to 24-hour \"HH:MM\" (e.g. \"5pm\" "
    "-> \"17:00\", \"3 o'clock\"/\"3pm\" -> \"15:00\", \"9:30 in the morning\" -> "
    "\"09:30\") -- always extract it, it is required to set up the rule at all. "
    "frequency MUST be exactly \"DAILY\", \"WEEKDAYS\", or \"WEEKLY\" -- "
    "\"every day\"/\"daily\" -> DAILY, \"on weekdays\"/\"Monday to Friday\" -> "
    "WEEKDAYS, a single named weekday (\"every Monday\") -> WEEKLY with "
    "day_of_week as that English weekday name; omit frequency entirely if not "
    "stated (defaults to DAILY). automation_action MUST be exactly \"SEND_DPR\" "
    "(send the daily report), \"COMPLIANCE_SUMMARY\" (who has/hasn't reported), "
    "or \"REMINDER\" (a message to nudge specific people) -- infer from what is "
    "asked for; \"send me the DPR\" -> SEND_DPR, \"tell me who didn't report\"/"
    "\"who hasn't submitted\" -> COMPLIANCE_SUMMARY, anything asking someone else "
    "to do/submit something -> REMINDER. audience MUST be exactly \"SELF\" "
    "(the sender themselves, e.g. \"send me\"/\"tell me\"), \"USERS\" (named "
    "people, e.g. \"ask Ilan or Hysam\" -> audience_names [\"Ilan\", \"Hysam\"]), "
    "\"ROLE\" (a job role, e.g. \"tell all site engineers\" -> audience_role "
    "\"site engineer\"), or \"NON_REPORTERS\" (only whichever of that role/group "
    "have not yet reported, e.g. \"tell site engineers to submit DPR if they "
    "haven't\"). audience_names is an array of the person names as stated, only "
    "for USERS. message is the sender's own reminder wording, only for REMINDER, "
    "omit for SEND_DPR/COMPLIANCE_SUMMARY.\n"
    "- add_project_member: member_name, role. Use this type when the user wants "
    "to add an EXISTING person (already has a Mesiri account) to an EXISTING "
    "project's team (e.g. \"add Rajesh to the project as site engineer\", \"make "
    "Priya a project manager on this project\") -- never a worker/labour "
    "attendance entry (that's labour_update). If the message also gives a phone "
    "number for someone who is clearly NOT an existing user yet, that's "
    "create_user instead. member_name is the person's name as stated -- always "
    "extract it, it will be matched against the organization's real users "
    "afterwards. role is an optional hint of what they should be (e.g. \"site "
    "engineer\", \"project manager\") -- omit entirely if not stated. Which "
    "project this adds to is NOT extracted here -- omit it entirely even if a "
    "project name is mentioned elsewhere in the message; that is resolved "
    "separately, same as site_create's project scope.\n"
    "- create_user: full_name, whatsapp_number, role. Use this type when the "
    "user wants to create a brand new person's WhatsApp access from scratch, "
    "i.e. a name AND a phone number for someone who does not already use "
    "Mesiri (e.g. \"add Rajesh, 9198765xxxxx, as site engineer\", \"create a "
    "user for Priya, phone 9876543210\") -- never add_project_member (that "
    "only ever adds an EXISTING user, never states a phone number for a new "
    "person) and never labour_update (a worker attendance line names someone "
    "physically on site today, not a request to give them app access). "
    "full_name is the new person's name -- always extract it. whatsapp_number "
    "is the phone number exactly as stated (digits, with or without a country "
    "code) -- always extract it, it is required to create access at all; if no "
    "number is stated anywhere in the message this is NOT create_user (it is "
    "more likely add_project_member or unrecognized). role is an optional hint "
    "(e.g. \"site engineer\", \"admin\") -- omit entirely if not stated."
)


# docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §9: only ever called on text
# extract() already returned semantic_type "unknown" for -- a single message
# describing several distinct requests has no representable single
# semantic_type, so "unknown" is that call's honest, correct answer, not a
# failure. This prompt's ONLY job is to say whether that "unknown" was really
# several requests at once and, if so, split them -- it must NOT classify
# each part itself (that is extract()'s job, run once per returned segment,
# unaltered) and must NOT reorder them (dependency order is derived later
# from what each segment's own extraction produces -- see
# planning/ordering.py). A message that is genuinely one thing, a greeting,
# or gibberish must return is_multi_intent: false, not a forced split --
# today's single "I didn't understand that" reply is the safe fallback, and
# a wrong split is not.
_DECOMPOSITION_PROMPT = (
    "The text may be in any language -- read it directly. It already failed "
    "single-request classification, meaning it may describe MULTIPLE distinct "
    "requests in one message (e.g. \"create a project called X, then a site "
    "called Y, then add a new user Z\" -- three separate requests: create a "
    "project, create a site, create a user).\n\n"
    "Decide: does this text state more than one distinct, actionable request? "
    "If yes, split it into separate sub-texts, each one grammatically complete "
    "on its own and in the SAME order the sender said them -- never reorder, "
    "never merge two requests into one, never invent a request the text does "
    "not state. If the text is really just one request, or is not an "
    "actionable request at all (a greeting, a question, gibberish), say so.\n\n"
    'Return strict JSON with keys: "is_multi_intent" (boolean), "segments" '
    '(array of strings -- empty when is_multi_intent is false). Do NOT '
    "classify what type each segment is; that happens separately."
)


_TRANSLATION_PROMPT = (
    "Translate the following text to English. Also identify the source language if possible. "
    'Return strict JSON with keys: "translated_text" and "detected_language". '
    "If it is already English, just return the text as translated_text and 'English' as detected_language."
)

_ENGLISH_LANGUAGE_LABELS = frozenset({"english", "en", "en-us", "en-in", "en-gb"})


def _downscale_image(
    image: bytes, mime_type: str | None, max_edge: int
) -> tuple[bytes, str | None]:
    """Shrink a photo to ``max_edge`` on its longest side before the vision
    call. A WhatsApp photo arrives at full camera resolution (1-3MB, several
    megapixels) and Gemini tiles it into far more vision tokens than reading
    a receipt or a roster needs -- analyze_image averaged 7.2s on real
    traffic, the largest single latency item left in the pipeline.

    Fails open in every direction: no Pillow installed, an unreadable or
    non-image payload, an already-small image -- all return the original
    bytes and mime type unchanged. A resize problem must never be the reason
    a receipt can't be read.

    EXIF orientation is baked in via exif_transpose before resizing, because
    re-encoding drops the EXIF block -- without that, a phone photo taken in
    portrait would reach Gemini rotated, which reads exactly like the model
    failing at handwriting.
    """
    if max_edge <= 0:
        return image, mime_type
    if mime_type and not mime_type.startswith("image/"):
        return image, mime_type
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
    except ImportError:
        return image, mime_type
    try:
        img = Image.open(BytesIO(image))
        if max(img.size) <= max_edge:
            # Already small enough -- return the original rather than
            # re-encoding it, so this stays a true no-op (and keeps whatever
            # EXIF the untouched bytes carry) for images that don't need it.
            return image, mime_type
        original_size = img.size
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            # JPEG has no alpha channel; P/RGBA/LA modes would fail to save.
            img = img.convert("RGB")
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        downscaled = buffer.getvalue()
        _log.info(
            "gemini.image_downscaled %sx%s -> %sx%s, %s -> %s bytes",
            *original_size,
            *img.size,
            len(image),
            len(downscaled),
        )
        return downscaled, "image/jpeg"
    except Exception:  # noqa: BLE001 -- see the fail-open note above
        _log.warning("gemini.image_downscale_failed, sending original", exc_info=True)
        return image, mime_type


def _is_english(detected_language: object) -> bool:
    """True only for a detected_language value that plainly says English --
    used to tell a legitimate no-op translation (source was already English,
    per _TRANSLATION_PROMPT's own instruction) apart from a translation that
    silently didn't happen for non-English input."""
    return bool(detected_language) and str(detected_language).strip().lower() in (
        _ENGLISH_LANGUAGE_LABELS
    )


def _looks_untranslated(translated_text: str) -> bool:
    """True if the text is still predominantly non-Latin script.

    A model that fails to translate can still vary punctuation/whitespace
    around the same untranslated words (a stray trailing "?", a re-typed
    quote), so an exact input/output string match is too easy to dodge
    while the actual words stay untranslated -- live case: a message ending
    in a Malayalam question mark came back with a *slightly* reformatted
    "translation" that was still 100% Malayalam, and exact-equality missed
    it entirely. Checking the script of the letters themselves is a much
    harder signal to accidentally slip past."""
    letters = [ch for ch in translated_text if ch.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for ch in letters if ord(ch) > 0x024F)  # past Latin Extended-B
    return (non_latin / len(letters)) > 0.3


class GeminiProvider:
    provider = "gemini"

    def __init__(self, settings: GeminiSettings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # lazy: only the gemini lane needs it

            api_key = self._settings.api_key.get_secret_value() if self._settings.api_key else None
            self._client = genai.Client(api_key=api_key)
        return self._client

    async def _generate(
        self,
        contents: Any,
        correlation_id: str | None,
        operation: str,
        *,
        json_mode: bool = False,
        thinking_budget: int | None = None,
    ) -> tuple[str, float]:
        client = self._get_client()

        async def _raw() -> Any:
            kwargs: dict[str, Any] = {"model": self._settings.model, "contents": contents}
            if json_mode or thinking_budget is not None:
                from google.genai import types

                config_kwargs: dict[str, Any] = {}
                if json_mode:
                    # Ask Gemini to return only the JSON object, no
                    # surrounding commentary -- without this, code-mixed
                    # input (e.g. a Malayalam sentence with an embedded
                    # English proper noun like a project name) sometimes
                    # prompts Gemini to add an explanatory sentence around
                    # the JSON, which _parse_json's naive fence-stripping
                    # can't handle (real bug: an inventory query naming a
                    # project failed translation this way). DeepSeek's
                    # adapter already forces its own equivalent
                    # (response_format=json_object); this is the same
                    # guarantee for Gemini. _parse_json below is hardened
                    # as a second line of defense in case this mode is
                    # ever unavailable/ignored by a future model.
                    config_kwargs["response_mime_type"] = "application/json"
                if thinking_budget is not None:
                    # 2.5-flash reasons by default even on schema-filling
                    # calls that don't benefit from it (traced: extract
                    # averaged 3.7s, translate 1.9s) -- thinking_budget=0
                    # turns that off. analyze_image deliberately doesn't
                    # pass this: reasoning measurably helps parsing messy
                    # handwritten attendance sheets, so it keeps the
                    # model's default budget.
                    config_kwargs["thinking_config"] = types.ThinkingConfig(
                        thinking_budget=thinking_budget
                    )
                kwargs["config"] = types.GenerateContentConfig(**config_kwargs)
            # The SDK's native async surface, not the sync one wrapped in
            # asyncio.to_thread as this used to be. to_thread borrows from the
            # default executor (~cpu_count+4 threads), so on a small container
            # concurrent messages queued behind each other *inside* the
            # measured latency -- which is why traced p99 ran far above p50
            # (extract: 3.3s p50 vs 11.6s p99) on the same prompt. Also makes
            # the call_with_resilience timeout actually cancel the in-flight
            # request instead of abandoning a thread that keeps running.
            return await client.aio.models.generate_content(**kwargs)

        resp, latency_ms = await call_with_resilience(
            _raw,
            provider=self.provider,
            operation=operation,
            timeout_seconds=self._settings.timeout_seconds,
            max_retries=self._settings.max_retries,
            correlation_id=correlation_id,
        )
        # BE-25: what this call used, for per-company cost tracking.
        usage.report(
            usage.ProviderUsage(
                provider=self.provider,
                operation=operation,
                model=self._settings.model,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
                **usage.gemini_usage(resp),
            )
        )
        text = getattr(resp, "text", None) or ""
        return text, latency_ms

    @staticmethod
    def _parse_json(text: str, correlation_id: str | None) -> dict[str, Any]:
        cleaned = (
            text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        try:
            data = json.loads(cleaned)
        except (ValueError, TypeError):
            # json_mode (response_mime_type="application/json") should prevent
            # this, but a model can still wrap the JSON in a clarifying
            # sentence -- disproportionately likely for code-mixed input
            # (e.g. a Malayalam sentence with an embedded English proper
            # noun). Fall back to extracting the outermost {...} object
            # from anywhere in the response before giving up.
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end > start:
                try:
                    data = json.loads(cleaned[start : end + 1])
                except (ValueError, TypeError) as exc:
                    raise malformed_output(
                        "gemini", str(exc), correlation_id=correlation_id
                    ) from exc
            else:
                raise malformed_output(
                    "gemini", "no JSON object found in response", correlation_id=correlation_id
                ) from None
        if not isinstance(data, dict):
            raise malformed_output(
                "gemini", "top-level JSON is not an object", correlation_id=correlation_id
            )
        return data

    async def analyze_image(
        self,
        image: bytes,
        *,
        mime_type: str | None = None,
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> VisionResult:
        import asyncio

        from google.genai import types  # lazy

        # Decode + resize + re-encode is blocking CPU work (~100-200ms for a
        # 3MB phone photo), so it goes to a thread rather than stalling the
        # event loop for every other in-flight message.
        image, mime_type = await asyncio.to_thread(
            _downscale_image, image, mime_type, getattr(self._settings, "max_image_edge", 1568)
        )
        part = types.Part.from_bytes(data=image, mime_type=mime_type or "image/jpeg")
        # The hint is what the user already told us this photo is (they tapped
        # a row in the image-purpose picker -- see channel/replies.py's
        # IMAGE_PURPOSE_SEMANTIC_HINT). Handing it to the vision model is worth
        # a lot on a poor-quality attendance sheet: knowing it is a roster
        # rather than a site photo is the difference between transcribing rows
        # and writing "a handwritten document on a clipboard". Still a nudge,
        # not an instruction to obey -- the model may classify it otherwise if
        # the image plainly disagrees, exactly as with the extraction hint.
        prompt = _VISION_PROMPT
        if hint:
            prompt = f"{_VISION_PROMPT}\n\nThe sender says this image is: {hint}."
        text, latency_ms = await self._generate(
            [prompt, part], correlation_id, "analyze_image", json_mode=True
        )
        data = self._parse_json(text, correlation_id)
        return VisionResult(
            document_classification=data.get("document_classification"),
            description=data.get("description"),
            raw_fields=data.get("fields", {}) or {},
            provider=self.provider,
            model=self._settings.model,
            latency_ms=latency_ms,
        )

    async def extract(
        self,
        text: str,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> ExtractionResult:
        prompt = f"{_EXTRACTION_PROMPT}\n\nText:\n{text}"
        if semantic_hint:
            prompt += (
                f'\n\nHint: the user selected the "{semantic_hint}" category just before '
                "sending this message. Prefer that semantic_type unless the text clearly "
                "indicates a different one -- never force it against clear evidence."
            )
        if expense_categories:
            options = ", ".join(f'"{c}"' for c in expense_categories)
            prompt += (
                f"\n\nIf semantic_type is expense, the organization's existing expense "
                f"categories are: {options}. Set the expense's `category` field to the "
                "closest matching one of these, verbatim. Only use a different value if "
                "none of these fit at all."
            )
        raw_text, latency_ms = await self._generate(
            prompt, correlation_id, "extract", json_mode=True, thinking_budget=0
        )
        data = self._parse_json(raw_text, correlation_id)
        return ExtractionResult(
            intents=parse_extracted_intents(data.get("intents")),
            detected_language=data.get("detected_language"),
            provider=self.provider,
            model=self._settings.model,
            latency_ms=latency_ms,
        )

    async def decompose(
        self, text: str, *, correlation_id: str | None = None
    ) -> DecompositionResult:
        prompt = f"{_DECOMPOSITION_PROMPT}\n\nText:\n{text}"
        raw_text, latency_ms = await self._generate(
            prompt, correlation_id, "decompose", json_mode=True, thinking_budget=0
        )
        data = self._parse_json(raw_text, correlation_id)
        return DecompositionResult(
            is_multi_intent=bool(data.get("is_multi_intent", False)),
            # Normalization (fewer than two segments is never a real split,
            # whatever is_multi_intent claimed) lives once, on the model
            # itself -- see DecompositionResult's validator.
            segments=[str(s) for s in (data.get("segments") or [])],
            provider=self.provider,
            model=self._settings.model,
            latency_ms=latency_ms,
        )

    async def understand_voice(
        self,
        audio: bytes,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> ExtractionResult:
        """Transcribe and extract in one call instead of two sequential
        round trips (transcribe() then extract() -- previously ~4.5s
        combined). Reuses _EXTRACTION_PROMPT verbatim, prefixed with
        transcription instructions and three extra JSON keys.

        Tradeoff accepted deliberately: understanding/pipeline.py's old
        _handle_voice checked the transcript against the deterministic
        greeting/whoami phrase lists *between* transcribe() and extract(),
        skipping the second call for a spoken "hi". That shortcut is gone --
        this one call always does the full extraction-shaped work, greeting
        or not. Traffic-weighted this should still be a net win (most voice
        traffic is real reports, not greetings), but it is a real behavior
        change, not just a relocation of code.
        """
        from google.genai import types  # lazy

        part = types.Part.from_bytes(data=audio, mime_type="audio/ogg")
        prompt = (
            "You will be given spoken audio. First transcribe it accurately "
            "in its own language. Then, exactly as if you were given the "
            "transcript as text directly, extract structured construction "
            "data from what was said -- read it in its own language, do not "
            "wait for a translation. In addition to the fields described "
            'below, also include in your JSON response: "transcript" '
            '(verbatim, original language), "translated_text" (English '
            "translation of the transcript; same as transcript if already "
            'English), "detected_language" (the source language\'s common '
            'English name, e.g. "Malayalam", "English").\n\n'
        ) + _EXTRACTION_PROMPT
        if semantic_hint:
            prompt += (
                f'\n\nHint: the user selected the "{semantic_hint}" category just before '
                "sending this message. Prefer that semantic_type unless the audio clearly "
                "indicates a different one -- never force it against clear evidence."
            )
        if expense_categories:
            options = ", ".join(f'"{c}"' for c in expense_categories)
            prompt += (
                f"\n\nIf semantic_type is expense, the organization's existing expense "
                f"categories are: {options}. Set the expense's `category` field to the "
                "closest matching one of these, verbatim. Only use a different value if "
                "none of these fit at all."
            )
        raw_text, latency_ms = await self._generate(
            [prompt, part], correlation_id, "understand_voice", json_mode=True, thinking_budget=0
        )
        data = self._parse_json(raw_text, correlation_id)
        transcript = (data.get("transcript") or "").strip()
        return ExtractionResult(
            transcript=transcript,
            translated_text=data.get("translated_text") or transcript,
            detected_language=data.get("detected_language"),
            intents=parse_extracted_intents(data.get("intents")),
            provider=self.provider,
            model=self._settings.model,
            latency_ms=latency_ms,
        )

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        correlation_id: str | None = None,
    ) -> str:
        prompt = f"{system_prompt}\n\n{user_prompt}"
        raw_text, _latency_ms = await self._generate(
            prompt, correlation_id, "generate_json", json_mode=True, thinking_budget=0
        )
        return (
            raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )

    async def translate_to_english(
        self, text: str, *, correlation_id: str | None = None
    ) -> TranslationResult:
        prompt = f"{_TRANSLATION_PROMPT}\n\nText:\n{text}"
        raw_text, latency_ms = await self._generate(
            prompt, correlation_id, "translate", json_mode=True, thinking_budget=0
        )
        data = self._parse_json(raw_text, correlation_id)
        translated_text = data.get("translated_text")
        if not translated_text:
            # A response that parses as JSON but omits (or blanks) the one
            # field this call exists to produce must not silently degrade
            # into "translation" that's just the original text handed back
            # -- that's indistinguishable from a working translation to
            # every caller downstream and was observed live: a Malayalam
            # report reached extraction/UI with no translation ever having
            # happened, no error, no warning anywhere. Same fail-loud
            # posture _parse_json already takes on unparseable JSON.
            raise malformed_output(
                "gemini",
                "translation response missing 'translated_text'",
                correlation_id=correlation_id,
            )
        detected_language = data.get("detected_language")
        if not _is_english(detected_language) and (
            translated_text.strip() == text.strip() or _looks_untranslated(translated_text)
        ):
            # A SECOND, distinct silent-failure mode found live after the
            # fix above shipped: Gemini can return a *populated*
            # translated_text that's just the original non-English text
            # echoed back -- sometimes byte-for-byte, sometimes with a
            # trivial punctuation/whitespace difference that dodges an
            # exact-equality check while the words themselves stay
            # completely untranslated (see _looks_untranslated). The
            # prompt explicitly allows identical output only when the
            # source is already English; anything else that's still
            # unchanged or still non-Latin script is a translation that
            # didn't happen, not a legitimate no-op.
            raise malformed_output(
                "gemini",
                f"translation returned untranslated text for detected_language={detected_language!r}",
                correlation_id=correlation_id,
            )
        return TranslationResult(
            translated_text=translated_text,
            detected_language=detected_language,
            provider=self.provider,
            model=self._settings.model,
            latency_ms=latency_ms,
        )

    async def transcribe(
        self,
        audio: bytes,
        *,
        language_hint: str | None = None,
        correlation_id: str | None = None,
    ) -> SpeechResult:
        from google.genai import types  # lazy

        # Previously just transcribed and copied the transcript into
        # translated_text verbatim -- no translation ever actually happened
        # here (unlike Sarvam's real combined STT+translate), which the
        # control panel's log viewer correctly flagged as "Translation did
        # not run" on every non-English voice message. extract() (post the
        # translate_to_english removal -- see understanding/pipeline.py)
        # already reads the raw transcript directly regardless, so this
        # isn't load-bearing for correctness, only for accurate logging --
        # but it's free to ask for in the same call, so ask for it. One
        # request, no extra round trip.
        part = types.Part.from_bytes(data=audio, mime_type="audio/ogg")
        prompt = (
            "Transcribe the audio accurately, in its own language. Then "
            "translate that transcript to English (if it's already English, "
            "translated_text is the same as the transcript). Return strict "
            'JSON with keys: "transcript" (verbatim, original language), '
            '"translated_text" (English), "detected_language" (the source '
            'language\'s common English name, e.g. "Malayalam", "English").'
        )
        text, latency_ms = await self._generate(
            [prompt, part], correlation_id, "transcribe", json_mode=True, thinking_budget=0
        )
        data = self._parse_json(text, correlation_id)
        transcript = (data.get("transcript") or "").strip()
        translated_text = data.get("translated_text") or transcript
        return SpeechResult(
            transcript=transcript,
            detected_language=data.get("detected_language"),
            translated_text=translated_text,
            provider=self.provider,
            model=self._settings.model,
            latency_ms=latency_ms,
        )
