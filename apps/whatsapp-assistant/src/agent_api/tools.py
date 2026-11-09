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
    #: PRC-32: path params the API declares as a UUID (the model is shown a plain string).
    uuid_path: tuple[str, ...] = ()

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
        "Current stock per site and material. Filter by project, site, material or category (category_id from "
        "material_categories; a main category includes its sub-categories). Each row names its category and main "
        "category.",
    ),
    Allowed("stock_check", "GET", "/materials/stock-check", "Current stock of one material at one site."),
    # PRC-17: "previous stock, used, balance" for a period, and what is running low.
    Allowed(
        "stock_summary", "GET", "/materials/stock-summary",
        "Stock for a period per site and material: opening (before the period), received, used, adjusted, closing, "
        "days left at the last week's use, on_order (still to come on open purchase orders) and running_low (which "
        "counts what is on order). Default period: the last 7 days to today. Filter by "
        "project, site, material or category (a main category includes its sub-categories). Each row names its "
        "category.",
    ),
    Allowed("list_receipts", "GET", "/materials/inflows",
            "Materials received: what, where, when, who recorded it, and each one's category. Filter by category "
            "(category_id from material_categories; a main category includes its sub-categories)."),
    Allowed("list_usage", "GET", "/materials/outflows",
            "Materials used or issued: what, where, when, who recorded it, and each one's category. Filter by "
            "category as list_receipts."),
    # PRC-04: the supplier goes in words (the API links it to the vendor); vendor_id is the dashboard's picker.
    # PRC-23: a delivery fills the one open purchase order it plainly belongs to by itself (the code decides);
    # no_order when they say it is not from any order. The saved line says which order, or offers the open ones.
    Allowed("record_receipt", "POST", "/materials/inflows", "Prepare a material receipt (material that arrived at a site)." + _WRITE,
            hide=("vendor_id", "purchase_order_line_id", "confirm_extra")),
    Allowed("delivery_order", "POST", "/procurement/orders/deliveries/{receipt_id}/order",
            "Prepare putting a delivery already saved (its id from list_receipts) on a purchase order line at its site "
            "(order: the order number they said, e.g. PO-0003), or taking it off its order (no order, no line_id: "
            "'not that order'). Stock does not change. If it is more than the order still has to come "
            "the save is refused and says so; prepare it again with confirm_extra only when they say the extra came."
            + _WRITE),
    Allowed("record_usage", "POST", "/materials/outflows", "Prepare a material usage (material used or issued at a site)." + _WRITE),
    Allowed("record_transfer", "POST", "/materials/transfers", "Prepare a transfer of material from one site to another." + _WRITE),
    # PRC-22: material requests -- what a site asks for before anyone orders it (Materials > Requests).
    Allowed("material_requests", "GET", "/procurement/requests",
            "Material requests (what the sites asked for, before it is ordered), most urgent first: status waiting "
            "(default), ordered, done, rejected, open or all; mine=true for this person's own. Each says who asked, "
            "for which site, needed by when, and per item what is at the site, already ordered, still to buy, and "
            "other sites that hold some; duplicates names other open requests for the same material."),
    Allowed("ask_for_material", "POST", "/procurement/requests",
            "Prepare a request for material a site NEEDS (not arrived yet): one material per request, the quantity "
            "in the unit they said, needed_by when they said a day, purpose in their words. If the project already "
            "has an open request for that material the save is refused and says who asked; prepare it again with "
            "confirm_duplicate only when they say it is extra." + _WRITE,
            hide=("lines", "source"), fixed=(("source", "whatsapp"),)),
    Allowed("decide_material_request", "POST", "/procurement/requests/{request_id}/decide",
            "Prepare the office's answer to a material request (find it with material_requests): ordered (note: "
            "the supplier if said), sent (from another site), rejected (note: the reason, required), or done "
            "(received). The person who asked is told. Admin, owner or project manager only." + _WRITE),
    # PRC-31: "make it 900 kg", "need it by Friday instead": the request is changed while it waits.
    Allowed("change_material_request", "PATCH", "/procurement/requests/{request_id}",
            "Prepare a change to a material request still waiting (find it with material_requests; their own, or "
            "any for the office): quantity (with unit_id) of a one-item request, needed_by, purpose. Only what they "
            "changed." + _WRITE, hide=("lines",)),
    Allowed("cancel_material_request", "POST", "/procurement/requests/{request_id}/cancel",
            "Prepare taking back a material request that is still waiting (their own, or any for the office)."
            + _WRITE),
    # PRC-09: orders to suppliers (Procurement > Purchase orders), the dashboard's own routes. Deliveries stay
    # record_receipt (a delivery fills its order by itself, PRC-23).
    Allowed("purchase_orders", "GET", "/procurement/orders",
            "Purchase orders to suppliers, the late ones first: status open (default: still to come, in part or "
            "not at all), part, received, closed, cancelled or all; filter by project or site. Each: its PO number "
            "(ref) and their own number (their_ref), the supplier, the site, who ordered it (created_by_name) and "
            "when, the expected date and urgency (late, soon), and per item what was ordered, has come and is still "
            "to come, with the request it covers."),
    Allowed("place_order", "POST", "/procurement/orders",
            "Prepare an order to a supplier (the office: admin, owner, project manager), placed now or already placed "
            "by phone: material_id + quantity in the unit they said (+ rate if said), supplier in their words, the "
            "site, expected_date when they said a day, their_ref when they gave the supplier's or their own number. "
            "Ordering a site's request ('order Arun's cement'): request_id (from material_requests) + supplier "
            "(+ rate), the items come from the request. If an open order or a waiting request already has that "
            "material the save is refused and says which; prepare it again with confirm_duplicate only when they "
            "say it is extra or separate." + _WRITE, hide=("lines", "vendor_id")),
    Allowed("change_order", "PATCH", "/procurement/orders/{order_id}",
            "Prepare a change to an open order (find it with purchase_orders): expected_date when it is moved, "
            "notes, their_ref, or the supplier while nothing has come. Only what they changed." + _WRITE,
            hide=("lines", "vendor_id")),
    Allowed("cancel_order", "POST", "/procurement/orders/{order_id}/cancel",
            "Prepare cancelling an order nothing came against (reason: their words, required). Its requests wait "
            "again and the people who asked are told." + _WRITE),
    Allowed("close_order", "POST", "/procurement/orders/{order_id}/close",
            "Prepare closing a part-received order: the rest will not come (reason required). A request still short "
            "waits to be ordered again." + _WRITE),
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
    # Wages and advances (LW-07, plan docs/plans/wages-and-labour-plan.md; SOP rule 22)
    Allowed("labour_teams", "GET", "/labour/teams",
            "Labour contractors (their teams): id, name, phone, workers on the register, man-days in the last 30 days."),
    Allowed("labour_advance_balances", "GET", "/labour/advances/balances",
            "Each worker's or labour contractor's advance: given, taken back from wages, still outstanding (project_id to "
            "narrow). Owner, finance and project managers only."),
    Allowed("give_labour_advance", "POST", "/labour/advances",
            "Prepare an advance to a worker on the register (worker_id), a labour team (vendor_id from labour_teams) or "
            "a person in words (payee_name), for a site (site_id) or project, from the money account they named "
            "(account_id from money_accounts; a site engineer's own cash box). It is taken back from their next "
            "wages." + _WRITE, hide=("source",), fixed=(("source", "whatsapp"),)),
    Allowed("wage_sheet", "GET", "/labour/wage-sheets/open",
            "This week's wages for a site (site_id) or project (project_id); a date for another week. Rows: payee_name, "
            "man_days, gross, overtime_amount, advances_recovered, deductions, net, paid, due, slip (the payment slip text, as it is "
            "them); status draft or approved; totals; changed (attendance changed since approval)."),
    Allowed("approve_wage_sheet", "POST", "/labour/wage-sheets/{sheet_id}/approve",
            "Prepare approving a week's wage sheet (from wage_sheet) so it can be paid." + _WRITE),
    Allowed("pay_wages", "POST", "/labour/wage-sheets/{sheet_id}/pay",
            "Prepare paying an approved wage sheet: one row (row_id; amount for part of it) or every row still due, "
            "from the money account they named (account_id)." + _WRITE, hide=("source",), fixed=(("source", "whatsapp"),)),
    # Work and issues
    Allowed("work_progress", "GET", "/progress/activities", "Work done / in progress per site, with dates and quantities."),
    Allowed(
        "record_work", "POST", "/progress/activities",
        "Prepare work done at a site on a day: what was done, and quantities in the unit they said. place: the "
        "floor / room in their words when they said one ('first floor Room-2', 'FF R2', 'onnam nila kitchen'); "
        "finished true only when they said that work is finished there ('plastering done in R2')." + _WRITE,
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
    Allowed(
        "add_bill_photo", "POST", "/expenses/{expense_id}/attachments",
        "Prepare adding this message's bill photo to an expense already saved (its expense_id from the facts or "
        "list_expenses); the photo is attached by itself." + _WRITE,
        hide=("data_base64", "content_type", "media_object_key"),
    ),
    # Site day: weather and conditions, the DPR
    Allowed("site_day", "GET", "/dpr/site-days/{site_id}", "One site's day: conditions (weather, hours lost), plan, what is reported."),
    Allowed(
        "set_site_conditions", "PATCH", "/dpr/site-days/{site_id}/conditions",
        "Prepare a site's conditions for a day: weather, hours lost, whether the site worked, tomorrow's plan." + _WRITE,
    ),
    Allowed("send_dpr", "POST", "/dpr/projects/{project_id}/send", "Prepare sending today's project DPR now." + _WRITE),
    # Machines and vehicles (NXT-11): the register, each machine's day, the hire check
    Allowed("machines", "GET", "/equipment",
            "The company's machines and vehicles: name, owned or hired and from whom, where each is, today's log, "
            "this month's hours, idle, breakdown, diesel and (for the roles that see spending) hire cost; service due."),
    Allowed("machine_logs", "GET", "/equipment/logs",
            "Machine day logs for a date or a period (hours worked, idle, breakdown, diesel, operator), with totals; "
            "for one date also the machines on site not logged yet."),
    Allowed(
        "log_machines", "POST", "/equipment/logs",
        "Prepare the day of one or more machines: hours worked, idle, breakdown (and why), diesel litres, operator, "
        "trips. The machine in their words ('JCB', 'JCB 2', 'mixer'); the site is where the machine is unless they "
        "said another. A second log of the same machine and day adds to that day." + _WRITE,
        hide=("source",), fixed=(("source", "whatsapp"),),
    ),
    Allowed(
        "add_machine", "POST", "/equipment",
        "Prepare adding a machine or vehicle to the company's list: its name as they call it, type, owned or hired, "
        "the hire company in words, the rate and per hour / day / month, the site it is at." + _WRITE,
    ),
    Allowed("move_machine", "POST", "/equipment/{machine_id}/move",
            "Prepare a machine going to another site (its id from `machines`)." + _WRITE),
    Allowed("off_hire_machine", "POST", "/equipment/{machine_id}/off-hire",
            "Prepare a hired machine sent back to the hire company (it stops earning hire)." + _WRITE),
    Allowed("hire_check", "GET", "/equipment/hire-check",
            "Per hired machine this month (or a period): hours recorded on site, what they come to at the rate, "
            "the hire bills and whether a bill asks for more. Only for the roles that see spending."),
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
    # PRC-35 (approved in session by the owner, 7 Nov 2026): pay an unpaid expense, or repay whoever paid from their
    # own pocket, from one of the company's accounts. The API lets only the owner, an admin or finance.
    Allowed("expense_payments", "GET", "/expenses/{expense_id}/payments",
            "What has been paid on one expense, from which account, and what is still unpaid."),
    Allowed("pay_expense", "POST", "/expenses/{expense_id}/payments",
            "Prepare paying an expense, or repaying the person who paid it from their own pocket, from one of the company's "
            "accounts (account_id from money_accounts; amount only when they paid part, else what is unpaid is paid). Find "
            "the expense with list_expenses (its paid_via says unpaid or own_pocket)." + _WRITE),
    # CC-09 / CC-10 (8 Nov 2026): what the company owes its suppliers, and paying one. The API shows balances only to
    # the roles that see spending, and lets only the owner, an admin or finance pay.
    Allowed("supplier_payables", "GET", "/finance/vendors/payables",
            "Who the company owes and how much: per supplier the balance (below zero: they hold our advance), what is "
            "overdue, deliveries not billed yet, open bills, unused advance, last payment; totals and how long it waited."),
    Allowed("supplier_account", "GET", "/finance/vendors/{vendor_id}/ledger",
            "One supplier's account (vendor_id from list_vendors): balance, open bills with due date and days late, "
            "deliveries not billed, advances not used, and every line with the running balance (date_from / date_to "
            "for a period)."),
    Allowed("pay_supplier", "POST", "/finance/vendors/{vendor_id}/payments",
            "Prepare paying a supplier (vendor_id from list_vendors) from one of the company's accounts (account_id from "
            "money_accounts) with the amount they said: it pays that supplier's oldest open bills first and what is "
            "left stays with them as an advance for the next bill. bill_ids [] when they said it is an advance only; "
            "reference for a UTR or cheque number; method (Bank transfer, UPI, Cheque, Cash) when said." + _WRITE),
    # PRC-11 (8 Nov 2026): a supplier's bill saved as an expense is matched to the deliveries the site recorded; when
    # not certain the answer offers them (unbilled_deliveries) and this puts the ones they confirm on the bill.
    Allowed("link_bill_deliveries", "POST", "/finance/vendors/{vendor_id}/bills/{expense_id}/deliveries",
            "Prepare putting deliveries the site recorded on a supplier's bill already saved as an expense (vendor_id "
            "and expense_id from that save; receipt_ids from its unbilled_deliveries), so they are not owed and "
            "counted twice." + _WRITE),
    # ST-04 (8 Nov 2026): the schedule. Read by everyone on the project; moved only by those who plan (the API checks).
    Allowed("schedule", "GET", "/projects/{project_id}/schedule",
            "The project's schedule (Gantt): each activity with planned start/end, progress measured from site work "
            "updates, state (late / behind / on_track / not_started / done), days_late, forecast_end, pushed_days "
            "(days the late work before it pushes it), critical; summary with forecast_finish and slip_days."),
    Allowed("update_schedule_activity", "PATCH", "/projects/{project_id}/schedule/activities/{activity_id}",
            "Prepare moving a schedule activity (activity_id from `schedule`): new start and/or end, or done=true when "
            "the PM says it is finished. The activities after it move with it." + _WRITE, hide=("preview", "push",
                                                                                                "clear_dates")),
    # MP-02/03 (8 Nov 2026): the material plan. Read only; the API lets only the roles that see the BOQ read it.
    Allowed("material_plan", "GET", "/projects/{project_id}/material-plan",
            "What the project will need of each material, from the BOQ work still to do x the materials per unit, "
            "over the schedule's dates, against stock and open orders (weeks: how far ahead, default 8; site_id to "
            "narrow): per material still_needed, weeks (need per week from this Monday), on_hand, on_order, "
            "short_day (the day it runs short), short_by, supplier and lead_days, order_by, order_now, and lines "
            "(the BOQ work it is for). Empty materials: no BOQ line has its materials set yet."),
    # NXT-03 (8 Nov 2026): money from clients. Owner, admin and finance only (D-N3; the API checks).
    Allowed("ra_bills", "GET", "/billing/ra-bills",
            "The RA (running) bills of the company's projects (project_id to narrow): ref (RA-03), status (draft, "
            "submitted, certified, cancelled), bill_date, client_name, gross, net (what the client pays)."),
    Allowed("receivables", "GET", "/billing/receivables",
            "What each client owes, most first: outstanding, by age (buckets 0_30, 31_60, 61_90, 90_plus), open_bills "
            "(ref, bill_date, due, received, left, days), unapplied (money received not on a bill yet), "
            "advance_received, last_received_on."),
    Allowed("record_client_receipt", "POST", "/billing/receipts",
            "Prepare recording money a client paid into one of the company's accounts (account_id from "
            "money_accounts): kind bill with ra_bill_id (from ra_bills) when they named a bill; advance for a "
            "mobilisation advance; on_account otherwise (project_id for those two). amount as they said it; "
            "received_on when not today; reference for a UTR or cheque number." + _WRITE),
    # CC-11 (8 Nov 2026): cost control. Read and written only by the roles that see the BOQ's rates (the API checks,
    # D-CC4) and only when the company has the Cost control module.
    Allowed("cost_today", "GET", "/cost/projects/{project_id}/variance",
            "Green / amber / red per BOQ line: the labour budget the work measured earned (done x labour rate) against "
            "the labour put on the line, for a period (date_from / date_to, default the last 7 days; one date for a "
            "day; site_id for one site). summary (colour, earned_labour, labour_cost, difference: below zero is over), "
            "lines worst first (colour, reason, done_quantity, unit, earned_labour, labour_cost, cost_per_unit against "
            "labour_rate), days (each day's colour), labour.not_on_a_line (labour on no line: not coloured), materials "
            "(earned vs bought for the project, not coloured)."),
    Allowed("budget_vs_actual", "GET", "/cost/projects/{project_id}/budget",
            "The project's budget against actual to date: kinds (labour, material, subcontract: budget, earned, actual "
            "spent, difference), and every BOQ line with planned_quantity, done_quantity, remaining_quantity, "
            "percent_done, budget_cost, earned, labour_cost; labour_not_on_a_line; work_not_on_a_line."),
    Allowed("materials_vs_boq", "GET", "/cost/projects/{project_id}/materials",
            "Per material with a norm on a BOQ line (CC-08): required_total (the whole BOQ), should_have_used (by the "
            "work done so far), received, used, on_hand, on_order, used_over_work (above zero: more used than the "
            "work accounts for), still_needed, short_by (to finish beyond on hand and on order), colour and reason; "
            "worst first. lines_without_norms: BOQ lines whose materials are not set."),
    Allowed("labour_not_on_boq", "GET", "/cost/projects/{project_id}/labour",
            "The project's attendance per site, day and trade (date_from / date_to, default the last 30 days; "
            "unallocated=true for only what is on no BOQ line): man_days, cost, on_lines (the BOQ lines it is on), "
            "not_on_a_line, suggested_line_id. Use its site_id, date and trade_key to put labour on a line."),
    Allowed("put_labour_on_boq", "PUT", "/cost/projects/{project_id}/labour",
            "Prepare putting a site's day of one trade on BOQ lines by man-days (site_id, date and trade from "
            "labour_not_on_boq; lines: [{line_id, man_days}] with line_id from budget_vs_actual's BOQ lines; it "
            "replaces the lines that day and trade was on; [] takes it off every line). Never more man-days than "
            "the day had." + _WRITE),
    # LP-04 (8 Nov 2026): progress by place. Read by everyone on the project; places are set up on the dashboard.
    Allowed("place_progress", "GET", "/projects/{project_id}/places/progress",
            "Progress floor by floor and room by room (place: a floor or room in their words, e.g. 'first floor'): "
            "per place, each kind of work done / in_progress / not_started, left (work not done there), done, photos, "
            "last_update. No match: options (the places to choose from). set_up false: no floors or rooms yet."),
    # DOC-05 / DR-08 (8 Nov 2026): the documents register. The API shows each person only what they may see.
    Allowed("find_documents", "GET", "/projects/{project_id}/documents/find",
            "Find a project document by what they call it (q: their words, e.g. 'S-101', 'column drawing', 'building "
            "permit'): current revisions only, best first, each with id, number, title, revision, folder, "
            "valid_until. Empty documents: nothing fits (folders says what the project has)."),
    Allowed("drawing_facts", "GET", "/projects/{project_id}/drawing-facts",
            "What the project's current drawings say (q narrows: 'slab', 'first floor', 'kitchen'): levels (text as "
            "written on the drawing; value in the drawing's own units; sheet), rooms (label, size_text, area as "
            "written, computed sqft / sqm, floor), floors, fixtures, checks (things to ask the architect); each "
            "names its drawing and revision. structure (a structural set): foundation (footings, concrete_cum, "
            "pcc_cum, steel_kg, steel_by_dia, cement_bags), footings (mark, count, size, depth, bars, columns), "
            "columns (mark, size, bars, ties, kg_per_m, count_on_plan), columns_kg_per_m, slabs (floor, mark, "
            "thickness, bars, steel_kg_per_sqm), notes (grades, SBC, covers), assumptions."),
    # NXT-05/06/07 (8 Nov 2026): subcontracts. Work orders, work measured on them, a subcontractor's bill (checked
    # by the API against measured and agreed), approving / rejecting a flagged bill, an advance, a statement.
    Allowed("list_work_orders", "GET", "/subcontracts/work-orders",
            "Work orders given to subcontractors (project_id / vendor_id to narrow): each with its lines (agreed, "
            "measured, billed, left), status, bills waiting for a check, payable now, retention held, advance left."),
    Allowed("work_order", "GET", "/subcontracts/work-orders/{wo_id}",
            "One work order: lines with agreed / measured / billed, measurements (and ones waiting for confirmation), "
            "bills with their check and deductions, history."),
    Allowed("create_work_order", "POST", "/subcontracts/work-orders",
            "Prepare a work order for a subcontractor: vendor_name (or vendor_id), project_id, site_id when said, name, "
            "lines [{description, unit (cum, sqm, sqft, rmt, nos...), quantity, rate}], retention_pct / advance_agreed "
            "only when said; issue true unless they said draft." + _WRITE),
    Allowed("measure_work", "POST", "/subcontracts/work-orders/{wo_id}/measurements",
            "Prepare work done on a work order line (line_id from work_order): quantity, measured_on when not today, "
            "notes." + _WRITE),
    Allowed("record_subcontract_bill", "POST", "/subcontracts/work-orders/{wo_id}/bills",
            "Prepare a subcontractor's bill on their work order: lines [{line_id, quantity, rate only when it differs}], "
            "amount when the bill's total is said, their_bill_no, bill_date. The API checks it against the work measured "
            "and the agreed rates: the answer says passed (payable after retention / advance / TDS) or flagged (why)."
            + _WRITE),
    Allowed("subcontract_bills_waiting", "GET", "/subcontracts/bills/waiting",
            "Subcontract bills waiting for a person (flagged by the check, or sent by the subcontractor), with why."),
    Allowed("approve_subcontract_bill", "POST", "/subcontracts/bills/{bill_id}/approve",
            "Prepare approving a flagged subcontract bill with the reason they gave (reason)." + _WRITE),
    Allowed("reject_subcontract_bill", "POST", "/subcontracts/bills/{bill_id}/reject",
            "Prepare rejecting a subcontract bill with the reason they gave (reason): nothing is owed for it." + _WRITE),
    Allowed("give_subcontract_advance", "POST", "/subcontracts/work-orders/{wo_id}/advance",
            "Prepare an advance to a subcontractor against a work order: account_id (money_accounts), amount; it is "
            "recovered from their bills." + _WRITE),
    Allowed("subcontractor_statement", "GET", "/subcontracts/vendors/{vendor_id}/statement",
            "A subcontractor's statement: each work order's agreed, done, billed, paid, retention held, advance left, "
            "and payable now."),
    # PRC-02: the code picks `category_id` (the model's `category` in words, then the API's rule on the name); a
    # guessed id would fail the save, so it stays hidden on add and update.
    Allowed("add_material", "POST", "/materials",
            "Prepare adding a material to the company's list (name, default unit, other names it is called, and "
            "category: its trade category in English as 'Main > Sub', from what the WHOLE name is ('Stainless steel "
            "sink' is 'Plumbing & CP > Sanitaryware', not steel; 'Plumbing & CP > Pipes', 'Electrical > Wires & "
            "cables'); the code places it in the company's own list)." + _WRITE,
            hide=("category_id",)),
    Allowed("update_material", "PATCH", "/materials/{material_id}",
            "Prepare changing a material in the list: its name, default unit, the other names it is called "
            "(aliases, e.g. 'kambi' for steel), or its category in words ('Plumbing & CP > Pipes'; the code moves it "
            "to the company's own category)." + _WRITE,
            hide=("category_id",)),
    # PRC-02c: a company that signed up on WhatsApp sets up and sees its material categories there too.
    Allowed("material_categories", "GET", "/materials/categories",
            "The company's material categories (main and sub-categories) and how many materials are in each, and how "
            "many materials have none."),
    Allowed("add_standard_categories", "POST", "/materials/categories/standard",
            "Prepare adding the builder's standard material categories (Structural, Electrical, Plumbing & CP, Fire "
            "protection, Gas, Lift, Finishing, with their sub-categories) and placing the materials that fit them. "
            "Safe to repeat; never moves a material already placed. Only for an admin or project manager." + _WRITE),
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
    # TM-30 (WEB-71): the dashboard's own route, added by scripts/allow_route.py.
    Allowed("add_person", "POST", "/projects/{project_id}/members/by-number", "Prepare adding someone NEW to the company, onto a project, by their name and WhatsApp number (typed, or said in a voice note), with a role (site engineer, project manager, finance, admin). Someone already in the company: add_project_member. fullName: as said; whatsappNumber: the digits as said; role: as said." + _WRITE),
    # TM-30: the dashboard's own route, added by scripts/allow_route.py.
    Allowed("waiting", "GET", "/approvals/waiting",
            "What is waiting for this person, urgent first then oldest: site reports with entries to confirm (today, "
            "yesterday), material requests to decide, subcontractor bills flagged or sent for approval, RA bills in "
            "draft, pay weeks whose wages are to approve or pay, their own tasks overdue or due today. Each item: kind, ref, "
            "title, detail, project_name, "
            "site_name, since, urgent; plus counts per kind and total. Read only: acting goes through each kind's own "
            "tool."),
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
        uuid_path: list[str] = []
        for param in operation.get("parameters", []):
            where = param.get("in")
            if where not in ("path", "query"):
                continue  # headers (Idempotency-Key) are the client's, not the model's
            name = param["name"]
            if where == "path" and (param.get("schema") or {}).get("format") == "uuid":
                uuid_path.append(name)
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
                "description": ("One short line naming this entry, shown when they confirm, in the reply language "
                                "(Manglish / Hinglish: Latin letters only), with material, work and site words in "
                                "English: \"30 bags cement, Green Villa\"."),
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
            uuid_path=tuple(uuid_path),
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
        # [249]: plain words only: the model copied tool names into the answer (a description can name another tool).
        from agent_api.reply_guard import without_tool_names

        line = without_tool_names(first, set(tools))[:80].strip()
        if tool.is_write:
            groups["record"].append(line)
        elif tool.path.startswith(("/dpr", "/timeline")):
            groups["reports"].append(line)
        else:
            groups["ask"].append(line)
    heads = {"record": "Record (the person sends it as a message, a voice note or a photo; one Save tap keeps it)",
             "ask": "Ask (answered from what is recorded: progress, issues, stock, attendance, expenses, materials)",
             "reports": "Reports (what happened on a day, the daily report, the timeline)"}
    return ("What Mesiri does (from your tools; answer in at most 6 short lines, plain words, never a tool name):\n"
            + "\n".join(f"{heads[g]}:\n" + "\n".join(f"- {line}" for line in lines)
                        for g, lines in groups.items() if lines))
