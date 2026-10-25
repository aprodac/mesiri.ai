"""Assistant reply rendering for the planner leg of the journey.

Counterpart to ``interactions/response_handler.py`` (which renders the
interaction leg). Both are pure string rendering: no business logic, no I/O.
Localisation and WhatsApp template migration happen here, not in callers.

Before this module the journey only acted on ``START_WORKFLOW``; ``CLARIFY``
and ``DIRECT_REPLY`` were computed, logged, and dropped, so every non-workflow
message fell through to ``understanding.runtime.format_reply`` -- a developer
diagnostic ("Type: unknown / Confidence: unusable") that was never meant to
reach a user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2

if TYPE_CHECKING:
    from workflows.entities import Candidate
    from workflows.registry import WorkflowDefinition

# Every workflows.registry import in this module is function-level and
# deliberately so: the registry imports every LangGraph builder, and those
# import back down into runtime, which imports this module. A module-level
# import here would close that cycle. The registry is a static table, so the
# repeated lookups cost nothing worth optimizing.

_EXAMPLES = '  • "50 bags of cement arrived"\n  • "20 bags of cement used for the foundation"'


@dataclass(frozen=True, slots=True)
class ListRow:
    """One tappable option in a WhatsApp list menu. Channel-agnostic content
    (id/title/description) -- transport-specific length limits are enforced
    where this actually gets sent (channel/whatsapp/outbound.py), not here."""

    id: str
    title: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class ReplySpec:
    """What to send back, decoupled from how. `list_rows` is set for a
    deterministic picker (category menu, image-purpose picker, etc.) or for
    a workflow's mid-flow slot-fill question when the node supplied
    candidates (see workflows/slots.py's `slot_options`); `buttons` is only
    ever set for a workflow confirmation prompt (see
    runtime/inbound_journey.py's _render_reply). At most one of the two is
    ever populated. The caller (runtime/inbound_journey.py) picks send_text
    vs send_list vs send_button based on which is set -- render_* functions
    never touch the transport."""

    text: str
    list_button_label: str | None = None
    list_rows: tuple[ListRow, ...] | None = None
    buttons: tuple[ListRow, ...] | None = None
    #: PNG shown above the body of a reply-button message (the receipt card).
    #: Only the button form carries it as a header; any other form sends it
    #: as its own image after the text (runtime/reply_dispatch.py).
    header_image: bytes | None = field(default=None, compare=False, repr=False)
    #: Request 91: a card (Stock) sent as ONE image with ``text`` as its caption,
    #: instead of the text and then the image. Only with no buttons or list; the
    #: text alone goes out if the image fails. Receipts leave this False.
    caption_image: bool = False


# The two reply buttons shown under every "Confirm this record?" prompt.
# Tapping one normalizes to NormalizedMessage.text = the title ("Yes"/"No"),
# which interactions/classifier.py already recognizes -- no new classification
# logic needed, only the send side.
CONFIRM_BUTTONS: tuple[ListRow, ...] = (
    ListRow("confirm_yes", "Yes"),
    ListRow("confirm_no", "No"),
)


def _category_rows() -> tuple[ListRow, ...]:
    """The top level of the tiered menu, derived from workflows/registry.py.

    Hand-listed until 2026-07-30, when it covered 5 of 26 registered
    workflows and one of those five ("Equipment & Machinery") pointed at a
    graph that was never built -- tapping it walked the user into the "not
    supported yet" reply. Deriving it means a workflow becomes discoverable
    the day it is registered and undiscoverable the day it isn't, with no
    second list to remember to update.
    """
    from workflows.registry import iter_menu_categories

    return tuple(
        ListRow(c.row_id, c.title, c.one_liner) for c in iter_menu_categories()
    )


# Kept as a module-level name because callers (admin/system_graph_router.py,
# tests) read it as a constant. Built once at import; the registry is a
# static table, so there is nothing to invalidate.
CATEGORY_ROWS: tuple[ListRow, ...] = _category_rows()

# Row ids from the flat pre-tiered menu, which can still arrive from a menu
# sitting in a user's chat history. Mapped to their nearest tiered
# equivalent rather than dropped, so an old tap opens the right submenu
# instead of falling through to the AI pipeline as unrecognized text.
# "cat_equipment" has no successor -- the graph was never built -- so it
# maps to the one thing that can still help, the full menu.
_LEGACY_CATEGORY_ROW_IDS: dict[str, str] = {
    "cat_expense": "cat_finance",
    "cat_site_issue": "cat_progress",
    "cat_equipment": "",
}

# Tapping "Material" asks this before anything else -- a button tap can't be
# garbled by a translation error the way speech/text can, so locking direction
# here means the common path never depends on transcription quality for this
# field. Row ids are matched verbatim by runtime/dependencies.py's category-tap
# handler (kept distinct from _MATERIAL_ROW_PREFIX = "mat_" in inbound_journey
# .py, which prefixes catalog *material* ids -- no collision).
MATERIAL_DIRECTION_BUTTONS: tuple[ListRow, ...] = (
    ListRow("dir_received", "Arrived"),
    ListRow("dir_used", "Used"),
)

_MATERIAL_ARRIVED_PROMPT = '📦 *Material Arrived* — tell me what arrived.\n\n"50 bags of cement arrived"'
_MATERIAL_USED_PROMPT = (
    '📦 *Material Used* — tell me what was used.\n\n"20 bags of cement used for the foundation"'
)


def render_material_direction_followup(direction: str) -> str:
    """The tailored prompt shown right after a Material direction button tap
    -- the example no longer needs to mention arrived/used since that's
    already settled, only what/how much."""
    return _MATERIAL_ARRIVED_PROMPT if direction == "received" else _MATERIAL_USED_PROMPT

def _menu_semantic_hints() -> dict[str, str]:
    """The semantic_type a menu tap hints extraction toward for the user's
    *next* message (see interactions/category_hint.py). A hint only ever
    nudges classification -- the model can still override it if the text
    clearly says otherwise (see the extraction prompts).

    Keyed by *workflow* row id, not category row id: under the tiered menu a
    category is far too coarse to bias extraction with. "Money" alone spans
    expense, transfer, petty cash, and reversal, and hinting any one of them
    off a category tap would bias four workflows toward whichever one lost
    the coin flip. Tapping the workflow itself is precise, so that is where
    the hint is set.

    The material pair is deliberately absent: their row ids (dir_received/
    dir_used) belong to the direction-lock handler, which sets the same hint
    plus a direction and must stay the only writer for them.
    """
    from workflows.registry import iter_user_initiable

    hints = {
        d.menu_row_id: d.semantic_hint
        for d in iter_user_initiable()
        if d.semantic_hint and not d.menu_row_id_override
    }
    # Stale taps from the pre-tiered flat menu, which hinted at category
    # level because that was the only level there was.
    hints.update(
        {
            "cat_material": "material_update",
            "cat_labour": "labour_update",
            "cat_expense": "expense",
            "cat_site_issue": "site_issue",
        }
    )
    return hints


CATEGORY_SEMANTIC_HINT: dict[str, str] = _menu_semantic_hints()

# A photo's purpose is never assumed from the AI's own guess at what the
# image shows -- every genuinely new image (not a tap resuming this very
# picker) is held (see interactions/pending_media.py) and this list is sent
# first, since a bare photo often arrives with no caption at all. Attendance
# took its own row here on 2026-07-26, exactly as this comment anticipated --
# a photographed attendance sheet is the most common way a site records who
# turned up, and it goes through this same mechanism rather than a
# labour-specific image path (Labour plan ADR-L3).
#: "Expense" and "Material Delivery" both describe a piece of paper from a
#: supplier, so their descriptions do the disambiguating rather than their
#: titles: a material invoice recorded as an expense would count the spend
#: without ever touching stock, and recorded as both would count it twice.
IMAGE_PURPOSE_ROWS: tuple[ListRow, ...] = (
    ListRow("img_material_invoice", "Material Delivery", "Supplier invoice or challan"),
    ListRow("img_expense", "Expense", "Something you paid for"),
    ListRow("img_attendance", "Attendance", "Who worked today"),
    ListRow("img_site_update", "Site Update", "Progress photo"),
)

# The semantic_type an image-purpose tap hints extraction toward for the
# HELD image being re-processed (see interactions/image_purpose.py). Same
# nudge-not-authority principle as CATEGORY_SEMANTIC_HINT above.
IMAGE_PURPOSE_SEMANTIC_HINT: dict[str, str] = {
    "img_material_invoice": "material_invoice",
    "img_expense": "expense",
    "img_attendance": "labour_update",
    "img_site_update": "general_site_update",
}


#: WA-65: the module a photo purpose belongs to. A row whose module is off
#: for the company is not offered -- tapping it could only answer "not
#: switched on" (audit PHO-08). Site Update is the DPR, always on.
IMAGE_PURPOSE_MODULE: dict[str, str] = {
    "img_material_invoice": "materials",
    "img_expense": "finance",
    "img_attendance": "labour",
}


def render_image_purpose_picker() -> ReplySpec:
    from workflows.registry import module_is_enabled

    return ReplySpec(
        text="📷 What is this photo for?",
        list_button_label="Choose one",
        list_rows=tuple(
            row for row in IMAGE_PURPOSE_ROWS if module_is_enabled(IMAGE_PURPOSE_MODULE.get(row.id))
        ),
    )


#: Buttons on the team-photo offer. "Upload Photo" is not a command Mesiri
#: can execute -- tapping it just acknowledges and waits for the picture --
#: but offering it beside Skip makes the choice explicit rather than leaving
#: the supervisor unsure whether silence counts as declining.
TEAM_PHOTO_BUTTONS: tuple[ListRow, ...] = (
    ListRow("team_photo_upload", "Upload Photo"),
    ListRow("team_photo_skip", "Skip"),
)


def render_team_photo_offer() -> ReplySpec:
    """Offered once attendance is recorded and the promotion step is settled.

    Recommended, never required: the attendance is already saved by the time
    this is sent, and the wording says so first, so a supervisor who ignores
    it has lost nothing. Blocking the record on a photo would make the
    fastest, most common report -- a plain headcount with no camera involved
    -- worse for everyone.
    """
    return ReplySpec(
        text=(
            "✅ Attendance recorded.\n\n"
            "📷 Want to add a team photo for today? It gets attached to this "
            "record as verification, and shows up later in reports and the "
            "site timeline.\n\n"
            "Send the photo now, or tap Skip."
        ),
        buttons=TEAM_PHOTO_BUTTONS,
    )


def render_team_photo_attached_reply() -> str:
    return "📷 Team photo attached to today's attendance. Thank you."


def render_team_photo_skipped_reply() -> str:
    """Deliberately closes the loop rather than going silent -- otherwise a
    tap on Skip looks identical to a message that failed to send."""
    return "👍 No problem — today's attendance is recorded and complete."


def render_completion_photo_followup() -> str:
    """#25 AI Follow-up: appended to the confirmation reply once an Activity
    is marked COMPLETED. Deliberately a plain question, not an interactive
    picker -- the expected answer is "send a photo" or "send nothing",
    neither of which benefits from a tappable list the way a multi-choice
    question would."""
    return "📷 Want to attach a completion photo?"


#: Buttons on the post-project-create setup offer. Tapping "Add a Site"
#: starts SITE_CREATE directly (project pre-known, see runtime/
#: inbound_journey/seeding.py's start_project_setup_followup) rather than
#: this button itself carrying the site name -- WhatsApp buttons have no
#: free-text input, so the tap only settles *which* project, and the site's
#: own name is asked as the workflow's normal first question.
PROJECT_SITE_OFFER_BUTTONS: tuple[ListRow, ...] = (
    ListRow("setup_add_site", "Add a Site"),
    ListRow("setup_skip_site", "Skip"),
)

#: Buttons on the post-site-create setup offer -- same reasoning as
#: PROJECT_SITE_OFFER_BUTTONS, one step later in the chain.
PROJECT_MEMBER_OFFER_BUTTONS: tuple[ListRow, ...] = (
    ListRow("setup_add_member", "Add a Teammate"),
    ListRow("setup_skip_member", "Skip"),
)


def render_project_site_offer(project_name: str | None) -> ReplySpec:
    """Offered once a new Project is confirmed and saved. A brand-new
    project always starts with zero sites -- nobody can log site work
    against it yet -- but the project is already saved by the time this is
    sent, so ignoring the offer costs nothing (same "recommended, never
    required" stance as render_team_photo_offer)."""
    label = f"*{project_name}*" if project_name else "This project"
    return ReplySpec(
        text=(
            f"🏗️ {label} needs at least one site before anyone can log work "
            "against it.\n\nWant to add one now?"
        ),
        buttons=PROJECT_SITE_OFFER_BUTTONS,
    )


def render_project_member_offer(alone: bool | None = None) -> ReplySpec:
    """Offered once a new Site is confirmed and saved -- the next gap in the
    same chain render_project_site_offer starts: a project with a site but
    no team still can't have anything logged against it by anyone but its
    creator (project_execution.py's persist_success only auto-adds the
    creator, and only when their role isn't org-wide).

    ``alone``: True when nobody but the sender is on the project (counted
    before the offer, [111]); None when it could not be counted, so no claim
    is made about the team."""
    text = (
        "👤 Only you are on this project so far.\n\nWant to add a teammate now?"
        if alone
        else "👤 Want to add a teammate to this project now?"
    )
    return ReplySpec(text=text, buttons=PROJECT_MEMBER_OFFER_BUTTONS)


def render_setup_offer_skipped_reply() -> str:
    """Deliberately closes the loop rather than going silent -- otherwise a
    tap on Skip looks identical to a message that failed to send, same
    reasoning as render_team_photo_skipped_reply."""
    return "👍 No problem — you can always do this later."


def render_setup_offer_expired_reply() -> str:
    """The offer's hint (ProjectSetupOfferStore) expired or was already
    consumed -- e.g. a double-tap, or answered more than 10 minutes ago.
    Never silently reopens the offer or guesses which project it was about;
    just says so and waits for whatever the user sends next."""
    return "That offer isn't open any more — just tell me what you'd like to do."


def render_evidence_attached_reply(*, count: int, activity_summary: str | None) -> str:
    """#2 Batch Media: confirmation after attaching a whole batch of "Site
    Update" photos to the open activity in ONE reply -- never one reply per
    photo (the gallery principle: a burst of N photos gets exactly one
    acknowledgement)."""
    noun = "photo" if count == 1 else "photos"
    if activity_summary:
        return f"📷 {count} {noun} attached to {activity_summary}."
    return f"📷 {count} {noun} attached to your current activity."


def render_no_open_activity_for_evidence_reply() -> str:
    """Honest reply when a "Site Update" photo batch has nothing open to
    attach to -- never silently dropped (P1: there is nothing here to
    attach evidence onto)."""
    return (
        "📷 Got your photo(s), but there's no activity in progress right now to attach "
        "them to. Describe the work first (e.g. \"started plastering Block A\"), then "
        "resend the photos."
    )


def render_batch_overflow_reply(*, held_count: int, remaining_count: int) -> str:
    """#2 Batch Media: when a batch of photos answered as Expense/Attendance
    has more than one photo, only the first goes through the normal
    single-report confirm flow this turn (concurrent confirmations for
    Expense/Attendance would collide with the single-active-workflow
    invariant -- see workflows/runtime.py -- and resolving that properly is
    #1 Multi-Activity's job, not this one's). The rest are named honestly
    rather than silently dropped."""
    plural = "photo" if remaining_count == 1 else "photos"
    return (
        f"(I'm only processing 1 of your {held_count} photos right now — please resend "
        f"the other {remaining_count} {plural} once this one is confirmed.)"
    )


# Field names as a site worker would say them, not as the schema spells them.
_FIELD_LABELS: dict[str, str] = {
    "material_name": "which material",
    "quantity": "how much",
    "unit": "the unit (bags, kg, tons)",
    "direction": "whether it arrived or was used",
    "amount": "the amount",
    "equipment_name": "which equipment",
    "duration_hours": "how many hours",
    "headcount": "how many workers",
    "supplier": "the supplier",
    "work_item": "what it was used for",
}


def _label(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " "))


def _greeting(timezone: str | None) -> str:
    """Time-of-day greeting in the user's timezone.

    Falls back to a neutral "Hello" rather than guessing: a wrong "Good morning"
    at 9pm is worse than no greeting at all.
    """
    if not timezone:
        return "Hello"
    try:
        hour = datetime.now(ZoneInfo(timezone)).hour
    except (ZoneInfoNotFoundError, ValueError):
        return "Hello"
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def render_clarify_reply(decision: PlannerDecisionV2) -> str:
    """Ask for the fields that are missing before the report can be recorded.

    ``missing_fields`` is never empty for a CLARIFY decision -- canonicalization
    only sets CLARIFICATION_REQUIRED when at least one required field is absent
    -- but render a safe fallback rather than an empty question if that changes.
    """
    missing = [_label(f) for f in decision.missing_fields]
    if not missing:
        return "I didn't quite catch that. Could you say it again?"
    if len(missing) == 1:
        asked = missing[0]
    else:
        asked = f"{', '.join(missing[:-1])} and {missing[-1]}"
    return f"Almost there — I still need {asked}."


def render_project_picker(projects: list[tuple[str, str, str | None]]) -> ReplySpec:
    """Ask which project a report belongs to. ``projects`` is a list of
    (project_id, name, location) -- plain tuples, not backend.ports.ProjectSummary,
    so this module stays within the channel/ dependency rule (mesiri_contracts.*
    only). Row id is "proj_{project_id}", matched verbatim by the caller that
    resumes the pending report once one is tapped."""
    rows = tuple(
        ListRow(f"proj_{project_id}", name, location or "")
        for project_id, name, location in projects[:10]
    )
    return ReplySpec(
        text="Which project is this for?",
        list_button_label="Choose project",
        list_rows=rows,
    )


def render_no_projects_reply() -> str:
    """The sender has no project to attach a report to at all -- distinct from
    the picker case so the message doesn't imply tapping will help."""
    return "You don't have any projects assigned yet. Ask your admin to add you to one first."


# Fixed id for "All Sites Combined" -- distinct from the per-site "site_{id}"
# prefix (never collides: real site ids are UUIDs, never the literal "all").
ALL_SITES_ROW_ID = "site_all"


def render_site_picker(sites: list[tuple[str, str]], *, allow_combined: bool) -> ReplySpec:
    """Ask which site a report/query belongs to, once its project is settled
    but the project has more than one site. ``sites`` is (site_id, name)
    pairs. Row id is "site_{site_id}", matched verbatim by the caller that
    resumes the pending report/query once one is tapped.

    ``allow_combined`` adds an "All Sites Combined" row -- only ever true for
    an inventory query (asking about stock can meaningfully span every site);
    a material report being recorded must always resolve to one real site,
    so recording never offers this option."""
    capacity = 9 if allow_combined else 10
    rows = [ListRow(f"site_{site_id}", name) for site_id, name in sites[:capacity]]
    if allow_combined:
        rows.append(ListRow(ALL_SITES_ROW_ID, "All Sites Combined"))
    text = (
        "Which site would you like — or everything combined?"
        if allow_combined
        else "Which site is this for?"
    )
    return ReplySpec(text=text, list_button_label="Choose site", list_rows=tuple(rows))


#: The material picker's escape hatch. Shares the "mat_" prefix so the
#: existing resume-leg prefix check still routes it, then is special-cased
#: before the id is read as a material_id -- same shape as
#: MEMBER_CANDIDATE_NONE_ROW_ID. A real material_id is always a UUID, so
#: this can never collide with one.
MATERIAL_CANDIDATE_NONE_ROW_ID = "mat_none"


def render_material_picker(candidates: list[tuple[str, str]]) -> ReplySpec:
    """Ask which catalog material a report refers to -- either because the
    reported name matched more than one active entry ("cement" -> OPC/PPC
    Cement), matched one only by substring (never auto-accepted -- see
    runtime/entity_resolution/material_resolution.py), or matched none at all
    (falls back to the org's whole active catalog so there's still something
    to pick from). ``candidates`` is (material_id, name) pairs. Row id is
    "mat_{material_id}", matched verbatim by
    resume_pending_report_with_material once one is tapped.

    The trailing "None of these" row carries MATERIAL_CANDIDATE_NONE_ROW_ID
    and falls through to the same create-offer/not-found handling a Missing
    result would show, exactly as render_member_candidate_picker's "Someone
    else" does. Without it this list is a trap rather than a question: once a
    lone substring guess stopped auto-resolving, a report of "cement" against
    a catalog holding only "Cement Paint" would otherwise offer that single
    wrong row and no way to decline it."""
    rows = tuple(
        ListRow(f"mat_{material_id}", name) for material_id, name in candidates[:9]
    ) + (ListRow(MATERIAL_CANDIDATE_NONE_ROW_ID, "None of these"),)
    return ReplySpec(
        text="Which material do you mean?",
        list_button_label="Choose material",
        list_rows=rows,
    )


# WhatsApp message types Mesiri can't act on yet, mapped to what to call them
# when declining. Keyed by Meta's raw `type` (kept on NormalizedMessage.
# metadata["raw_type"]) rather than InputModality, because every one of these
# normalizes to the same UNKNOWN modality -- the raw type is the only thing
# left that can make the reply specific.
_UNSUPPORTED_TYPE_LABELS: dict[str, str] = {
    "document": "documents or PDFs",
    "video": "videos",
    "sticker": "stickers",
    "location": "location pins",
    "contacts": "shared contacts",
    # A voice note normalizes to VOICE and never reaches here; a music/audio
    # file (audio.voice falsy) does.
    "audio": "audio files",
}

# Not user-authored content, so declining would be noise rather than help:
# a reaction is an emoji tap on one of Mesiri's own replies (answering every
# 👍 with "I can't handle this" would be maddening), and `system` is Meta's
# own notice (e.g. the sender changed their number). Both are dropped
# quietly -- still logged, just not replied to.
SILENTLY_IGNORED_RAW_TYPES: frozenset[str] = frozenset({"reaction", "system", "order"})


def render_unsupported_media_reply(raw_type: str | None) -> str:
    """Tell the sender their message arrived but can't be acted on yet.

    Silence is the one outcome that must never happen here: a field worker
    who gets no answer can't tell "Mesiri ignored my PDF" from "Mesiri is
    down", so they either resend or assume the report landed when it didn't.
    Always names a concrete way to get the same information in -- a decline
    that doesn't say what to do instead just moves the dead end.

    Callers must check SILENTLY_IGNORED_RAW_TYPES first; this always returns
    a reply.
    """
    label = _UNSUPPORTED_TYPE_LABELS.get(str(raw_type or ""), "this kind of message")
    return (
        f"📎 Got your message — but I can't read {label} yet.\n\n"
        "Send it one of these ways instead:\n"
        "  • 📷 A photo (of a bill, delivery note, or the site)\n"
        "  • 🎤 A voice note\n"
        "  • ⌨️ Or just type it out"
    )


def render_material_create_offer(name: str) -> ReplySpec:
    """The reported material isn't in the catalog and the sender's role is
    allowed to add one (see the org's whatsapp_material_create_roles setting)
    -- offer to add it inline instead of dead-ending the report the way
    render_material_not_found_reply does. Row ids "matnew_yes"/"matnew_no",
    matched verbatim by resume_pending_report_with_material_create."""
    return ReplySpec(
        text=(
            f'"{name}" isn\'t in your materials catalog yet.\n\n'
            "Add it and continue with this report?"
        ),
        buttons=(ListRow("matnew_yes", "Yes, add it"), ListRow("matnew_no", "No")),
    )


def render_material_create_unit_picker(name: str, units: list[tuple[str, str]]) -> ReplySpec:
    """Adding `name` to the catalog needs a Stock Unit and the report's own
    text didn't carry a recognizable one. Row ids "matunit_{unit_id}",
    matched verbatim by resume_pending_report_with_material_unit_choice.

    A material's Stock Unit is fixed for its lifetime in V1 (no unit
    conversion), so this is asked once, up front, rather than inferred and
    silently locked in."""
    rows = tuple(ListRow(f"matunit_{unit_id}", display) for unit_id, display in units[:10])
    return ReplySpec(
        text=f"What unit is {name} measured in?",
        list_button_label="Choose unit",
        list_rows=rows,
    )


def render_material_create_declined_reply(name: str) -> str:
    """The sender declined to add the material. Nudge toward a spelling
    mistake rather than just closing: a near-miss name ("Fevikol" vs
    "Fevicol") is the most likely reason a real material didn't match, and
    adding it under the wrong spelling would fragment the catalog."""
    return (
        f'Ok — "{name}" wasn\'t added.\n\n'
        "If it was a spelling mistake, resend the report with the correct name."
    )


def render_material_created_reply(name: str, unit_display: str) -> str:
    """Confirms the catalog entry before the held report resumes, so the
    unit the material is now permanently tracked in is stated explicitly
    rather than only showing up later in the confirmation's field list."""
    return f"✅ Added {name} to your catalog, tracked in {unit_display}."


def render_material_not_found_reply(name: str) -> str:
    """No catalog material matched at all and the org's catalog is empty --
    distinct from the picker case for the same reason render_no_projects_reply
    is: tapping won't help, there's nothing to choose from."""
    return f'I couldn\'t find "{name}" in the materials catalog. Ask your admin to add it first.'


# ---------------------------------------------------------------------------
# Member-name resolution (ENTITY_RESOLUTION_PLAN.md) -- ADD_PROJECT_MEMBER's
# member_name gate. Mirrors the material picker/create-offer pair above in
# shape and row-id convention exactly; the difference is what backs the
# match (member_resolution.py's near-match scoring, not catalog ILIKE) and
# that Missing chains into a real second workflow (CREATE_USER) rather than
# a single inline record.
# ---------------------------------------------------------------------------

#: Tapped when none of the offered candidates was who the sender meant --
#: falls through to the same create-offer Missing would have shown, matched
#: verbatim by resume_pending_report_with_member_candidate.
MEMBER_CANDIDATE_NONE_ROW_ID = "member_none"


def render_member_candidate_picker(
    name_hint: str, candidates: tuple[Candidate, ...]
) -> ReplySpec:
    """Ask which active user a project-member name hint refers to -- the
    reported name matched nobody exactly but scored close to one or more
    real people (member_resolution.resolve_name_hint's Ambiguous case).
    ``candidates`` is workflows.entities.Candidate instances. Row id
    "member_{entity_id}", matched verbatim by
    resume_pending_report_with_member_candidate; the trailing "Someone
    else" row carries MEMBER_CANDIDATE_NONE_ROW_ID and falls through to the
    same create-offer a Missing result would show.

    Never auto-picks even a single, high-scoring candidate -- see
    workflows/entities.py's Ambiguous docstring on why this always asks."""
    rows = tuple(
        ListRow(f"member_{c.entity_id}", c.display_name) for c in candidates[:9]
    ) + (ListRow(MEMBER_CANDIDATE_NONE_ROW_ID, "Someone else"),)
    return ReplySpec(
        text=f'I couldn\'t find an exact match for "{name_hint}" — did you mean one of these?',
        list_button_label="Choose one",
        list_rows=rows,
    )


#: The automation-audience picker's escape hatch. Distinct prefix again --
#: three person-pickers now coexist (member, petty-cash recipient, audience)
#: and each continues a different held request.
AUDIENCE_CANDIDATE_NONE_ROW_ID = "aud_none"


def render_audience_candidate_picker(
    name_hint: str, candidates: tuple[Candidate, ...]
) -> ReplySpec:
    """Ask which active user one of an automation's audience names refers to.

    Asked one name at a time: "remind Ilan and Hysam every Monday" resolves
    Ilan silently and stops on Hysam, and answering it re-runs the gate,
    which either asks about the next unresolved name or lets the automation
    through. One question per unknown name is more taps than a single
    summary, but it keeps the request alive -- the alternative was making
    the user retype the whole sentence (ENTITY_RESOLUTION_PLAN.md §5.3).

    Row id "aud_{entity_id}", matched verbatim by
    resume_pending_report_with_audience_candidate."""
    rows = tuple(ListRow(f"aud_{c.entity_id}", c.display_name) for c in candidates[:9]) + (
        ListRow(AUDIENCE_CANDIDATE_NONE_ROW_ID, "None of these"),
    )
    return ReplySpec(
        text=f'I couldn\'t find "{name_hint}" — who should I remind?',
        list_button_label="Choose one",
        list_rows=rows,
    )


def render_audience_not_found_reply(name_hint: str) -> str:
    """Nothing close enough to offer for one of the audience names.

    Stops rather than quietly creating the automation for everyone else:
    a reminder that silently omits someone is worse than one that was never
    created, because nobody finds out until the thing it was meant to
    prevent has already happened."""
    return (
        f'I couldn\'t find an active user called "{name_hint}" to remind.\n\n'
        "Check the spelling, or ask an admin to add them first."
    )


#: The petty-cash recipient picker's escape hatch. Distinct prefix from
#: MEMBER_CANDIDATE_NONE_ROW_ID's "member_" so the two resume legs never
#: catch each other's taps -- both resolve a person, but one continues an
#: ADD_PROJECT_MEMBER and the other an issuance of cash.
PETTY_CASH_RECIPIENT_NONE_ROW_ID = "pcr_none"


def render_petty_cash_recipient_picker(
    name_hint: str, candidates: tuple[Candidate, ...]
) -> ReplySpec:
    """Ask which active user a petty-cash recipient name refers to -- the
    reported name matched nobody exactly but scored close to one or more real
    people (name_matching.resolve_name_hint's Ambiguous case).

    Same shape as render_member_candidate_picker, deliberately with sharper
    copy: this one decides *who receives money*, so the question names the
    amount's destination rather than reading as a generic disambiguation.
    Row id "pcr_{entity_id}", matched verbatim by
    resume_pending_report_with_petty_cash_recipient; the trailing "None of
    these" row carries PETTY_CASH_RECIPIENT_NONE_ROW_ID and stops the
    issuance rather than guessing.

    Never auto-picks even a single high-scoring candidate -- see
    workflows/entities.py's Ambiguous docstring, and note the stakes here are
    higher than a project membership: a wrong pick moves cash onto the wrong
    person's advance account."""
    rows = tuple(ListRow(f"pcr_{c.entity_id}", c.display_name) for c in candidates[:9]) + (
        ListRow(PETTY_CASH_RECIPIENT_NONE_ROW_ID, "None of these"),
    )
    return ReplySpec(
        text=f'I couldn\'t find an exact match for "{name_hint}" — who is this for?',
        list_button_label="Choose one",
        list_rows=rows,
    )


def render_petty_cash_recipient_not_found_reply(name_hint: str) -> str:
    """Nothing close enough to offer. Stops before a draft is built rather
    than after the user confirms one -- the pre-Phase-4 behaviour left
    recipient_account_id unset, built the draft anyway, and let
    transfer_validation reject it once the user had already tapped Yes
    (ADR-E1: resolution belongs before the draft, not after)."""
    return (
        f'I couldn\'t find an active user called "{name_hint}" to issue cash to.\n\n'
        "Check the spelling, or ask an admin to add them first."
    )


def render_member_create_offer(name_hint: str) -> ReplySpec:
    """No active user matched at all, and the sender's role is allowed to
    create one (WorkflowKey.CREATE_USER's allowed_roles, checked by the
    caller before this is ever rendered -- ADR-E5) -- offer to create them
    inline and finish the original add-to-project request once they exist,
    instead of the old dead-end "couldn't find an active user named X."
    Row ids "membernew_yes"/"membernew_no", matched verbatim by
    resume_pending_report_with_member_create_offer."""
    return ReplySpec(
        text=(
            f'"{name_hint}" isn\'t an active user yet.\n\n'
            "Create them and continue adding them to the project?"
        ),
        buttons=(ListRow("membernew_yes", "Yes, create"), ListRow("membernew_no", "No")),
    )


#: Row ids for the whole-plan preview's Yes/No (docs/execution/
#: COMPOSITE_REQUEST_PLAN_LAYER.md §8) -- matched verbatim by
#: resume_pending_plan_confirmation. Distinct from CONFIRM_BUTTONS'
#: "confirm_yes"/"confirm_no": those are for a single workflow's own draft
#: confirmation; a plan preview confirms the WHOLE plan before any single
#: step's workflow has even started, so it needs its own ids even though
#: both buttons' titles read "Yes"/"No" the same way.
PLAN_CONFIRM_YES_ROW_ID = "plan_confirm_yes"
PLAN_CONFIRM_NO_ROW_ID = "plan_confirm_no"
#: §12's open question, resolved: EDIT means "pick one step to drop, then
#: re-preview" -- not a free-text rewrite. Tapping this shows
#: render_plan_edit_picker; PLAN_EDIT_CANCEL_ROW_ID backs out of that picker
#: with nothing changed; PLAN_REMOVE_ROW_PREFIX + a step_id removes it (and
#: its dependents -- see PlanStore.remove_step) and returns to the preview.
PLAN_EDIT_ROW_ID = "plan_edit"
PLAN_EDIT_CANCEL_ROW_ID = "plan_edit_cancel"
PLAN_REMOVE_ROW_PREFIX = "plan_remove_"


def render_plan_preview_reply(plan_text: str) -> ReplySpec:
    """The whole-plan preview (§8) -- one numbered line per step (already
    rendered by planning/preview.py's render_plan_preview, kept out of this
    module since it needs Plan/PlanStep, which channel/ must not depend on),
    plus Yes/No/Edit. Three buttons is Meta Cloud API's own cap
    (channel/whatsapp/outbound.py's _REPLY_BUTTON_MAX_COUNT) -- there is no
    room for a fourth without dropping one of these three."""
    return ReplySpec(
        text=plan_text,
        buttons=(
            ListRow(PLAN_CONFIRM_YES_ROW_ID, "Yes"),
            ListRow(PLAN_CONFIRM_NO_ROW_ID, "No"),
            ListRow(PLAN_EDIT_ROW_ID, "Edit"),
        ),
    )


def render_plan_edit_picker(steps: list[tuple[str, str]]) -> ReplySpec:
    """Which step to drop. ``steps`` is a list of (row_id, description)
    pairs the caller already resolved to plain text
    (planning/preview.py's describe_step) -- plain tuples, not Plan/PlanStep,
    same reasoning as render_project_picker's own (project_id, name,
    location) tuples: this module stays within channel/'s dependency rule.

    A "Keep all" row up front, mirroring render_material_picker/
    render_member_candidate_picker's own escape hatch for a picker the
    sender opened but didn't actually want to act on.
    """
    # Not truncated here -- channel/whatsapp/outbound.py's send_list already
    # truncates every row's title/description to Meta's own limits at send
    # time (the one place that already owns that responsibility for every
    # other picker in this module).
    rows = [ListRow(PLAN_EDIT_CANCEL_ROW_ID, "Keep all", "Don't remove anything")]
    rows.extend(
        ListRow(row_id, f"Step {i}", description) for i, (row_id, description) in enumerate(steps, start=1)
    )
    return ReplySpec(
        text="Which step should I remove?",
        list_button_label="Choose a step",
        list_rows=tuple(rows),
    )


def render_plan_cancelled_reply() -> str:
    return "Okay, I won't do any of that."


def render_plan_confirmation_expired_reply() -> str:
    """The plan's TTL (PlanStore, 30 minutes) lapsed before the sender
    answered Yes/No -- mirrors render_setup_offer_expired_reply's honest
    "this offer is gone" wording rather than pretending to still hold it."""
    return "That request has expired — please resend it."


def render_plan_emptied_by_edit_reply() -> str:
    """Every step was removed via EDIT -- nothing left to confirm. Distinct
    wording from render_plan_cancelled_reply (an explicit No) since this is
    a side effect of repeated removal, not a single deliberate decision."""
    return "That removed everything in this request — please resend it."


def render_member_create_declined_reply(name_hint: str) -> str:
    """The sender declined to create the user. Nudge toward a spelling
    mistake first, same reasoning as render_material_create_declined_reply
    -- a near-miss transliteration is the likeliest reason a real, already-
    registered person didn't match."""
    return (
        f'Ok — "{name_hint}" wasn\'t added to the project.\n\n'
        "If it was a spelling mistake, resend the request with the correct name."
    )


def render_member_not_found_reply(name_hint: str) -> str:
    """No active user matched, and the sender's role isn't allowed to create
    one (ADR-E5) -- distinct from render_member_create_offer for the same
    reason render_material_not_found_reply is distinct from the create
    offer: there is nothing left for this sender to tap."""
    return (
        f'I couldn\'t find an active user named "{name_hint}", and your role '
        "can't add a new one. Ask your admin to add them first."
    )


def render_usage_exceeds_stock_reply(
    *, material_name: str, unit: str, requested: float, available: float
) -> ReplySpec:
    """A usage report's quantity exceeds what's actually in stock -- block it
    instead of the old cosmetic-only confirmation warning (workflows/material
    /nodes.py's _low_stock_warning let the user tap Yes anyway and stock went
    negative, the real-world bug this fixes). Row ids "stock_cap"/
    "stock_arrival"/"stock_cancel", matched verbatim by
    resume_pending_report_with_stock_choice."""
    return ReplySpec(
        text=(
            f"⚠️ You reported using {requested:g} {unit} of {material_name}, but "
            f"only {available:g} {unit} is in stock — that's not possible.\n\n"
            "What would you like to do?"
        ),
        buttons=(
            ListRow("stock_cap", "Cap at available"),
            ListRow("stock_arrival", "It's an arrival"),
            ListRow("stock_cancel", "Cancel"),
        ),
    )


def render_unit_mismatch_reply(*, material_name: str, unit_id: str, unit_display: str) -> ReplySpec:
    """The reported unit doesn't match `material_name`'s Stock Unit (or wasn't
    recognized at all) -- ask a single yes/no clarification naming the
    material's actual unit, never a free-standing list of every unit in the
    system (a material only ever has one valid unit in V1, so a global picker
    would let the user pick something incompatible). Row ids "unit_yes_{id}"/
    "unit_no", matched verbatim by resume_pending_report_with_unit."""
    return ReplySpec(
        text=f"{material_name} is tracked in {unit_display} — record this as {unit_display}?",
        buttons=(ListRow(f"unit_yes_{unit_id}", "Yes"), ListRow("unit_no", "No")),
    )


def render_greeting_menu(
    *, timezone: str | None = None, is_first_message: bool = False
) -> ReplySpec:
    """The greeting + tappable category menu. Decision-independent (no
    PlannerDecisionV2 needed) so it can be called from two places: the AI
    path (render_direct_reply's UNRECOGNIZED case, below) and the
    deterministic pre-pipeline fast path (InteractionHandler.
    handle_greeting_trigger) that recognizes "hi"/"menu"/etc. without ever
    touching the AI pipeline. A first-ever message gets a short intro; a
    returning "hi" doesn't need re-introducing every time (see Infobip's
    greeting UX guidance).
    """
    if is_first_message:
        body = (
            f"{_greeting(timezone)}. I'm Mesiri — I record your daily site updates over "
            f"WhatsApp, no app needed. Just tell me what happened, like:\n{_EXAMPLES}\n\n"
            "Or pick what you're reporting:"
        )
    else:
        body = f"{_greeting(timezone)}. What are you reporting today?"

    return ReplySpec(
        text=body,
        list_button_label="Choose one",
        list_rows=CATEGORY_ROWS,
    )


def render_direct_reply(
    decision: PlannerDecisionV2, *, timezone: str | None = None, is_first_message: bool = False
) -> ReplySpec:
    """Reply when there is no workflow to start: a greeting, a question, or
    something the assistant could not place.

    Both cases can carry a list menu. Greetings and unparseable text get the
    category menu -- that is exactly where a worker who doesn't know what to
    type benefits from tappable categories. A question gets whichever
    capabilities runtime/capability_help.py matched to it, falling back to
    the same category menu when nothing matched.
    """
    if decision.reason is CanonicalEventType.GENERAL_QUESTION_ASKED:
        return render_capability_answer(
            decision.metadata.get("capability_matches"),
            role=decision.metadata.get("actor_role"),
            timezone=timezone,
            kind=decision.metadata.get("capability_kind"),
            question=decision.metadata.get("capability_question"),
            smalltalk_reply=decision.metadata.get("smalltalk_reply"),
        )
    # UNRECOGNIZED — greetings land here (when they slip past the
    # deterministic fast path, e.g. text/handle_greeting_trigger didn't cover
    # every phrasing), as does anything genuinely unparseable.
    return render_greeting_menu(timezone=timezone, is_first_message=is_first_message)


def render_capability_answer(
    matched_keys: object,
    *,
    role: str | None = None,
    timezone: str | None = None,
    kind: object = None,
    question: object = None,
    smalltalk_reply: object = None,
) -> ReplySpec:
    """Answer a "how do I ...?" question with the capabilities that match it.

    ``matched_keys`` is whatever runtime/capability_help.py put on the
    decision metadata -- a list of WorkflowKey *values* (plain strings, since
    it has been through a Pydantic model). Anything else, including None and
    the empty list, is treated as "nothing matched" and answered with the
    full menu, which is a genuinely good answer to "what can you do?" rather
    than a failure state. This function stays pure: the matching already
    happened upstream, the same way WHO_AM_I's profile is injected before
    its node ever runs.

    Rows carry the same wf_* ids the tiered menu uses, so tapping a
    suggestion runs the existing tap handler -- prompt, examples, and
    extraction hint -- with no separate plumbing for help.
    """
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from workflows.registry import get_definition

    if kind == "smalltalk":
        # Meta talk / chit-chat / a complaint about the bot: one short line,
        # no menu. Any other kind (None, garbage) is a capability question.
        # [75] the model's own answer (runtime/capability_help.py) is the normal
        # path; the fixed variants only apply when it was never asked.
        if isinstance(smalltalk_reply, str) and smalltalk_reply.strip():
            return ReplySpec(text=smalltalk_reply)
        return ReplySpec(text=_pick_smalltalk(question))

    definitions = []
    if isinstance(matched_keys, (list, tuple)):
        for raw in matched_keys:
            try:
                definition = get_definition(WorkflowKey(raw))
            except ValueError:
                continue
            if definition is not None and definition.user_initiable:
                definitions.append(definition)

    if not definitions:
        # No match, or a broad "what can you do?" -- the menu answers both.
        # Deliberately not render_greeting_menu(): its copy opens with
        # "Hello. What are you reporting today?", which answers a question
        # with a greeting and reads as though the question was ignored.
        return _render_capability_overview(role)

    if len(definitions) == 1:
        # One confident match reads better as the answer itself than as a
        # one-row list the user still has to tap.
        return ReplySpec(text=f"Yes — {_render_workflow_prompt(definitions[0])}")

    rows = tuple(
        ListRow(d.menu_row_id, d.title, d.one_liner)
        for d in definitions
        if _visible_to_role(d, role)
    )
    if not rows:
        return _render_capability_overview(role)
    return ReplySpec(
        text="Sounds like one of these — tap the one you mean:",
        list_button_label="Choose one",
        list_rows=rows,
    )


_OVERVIEW_INTRO = "Here's what I can do:"
_OVERVIEW_TELL = (
    "1. Just send me what happened on site, e.g. “6 masons and 4 helpers, slab work on floor 3 done”"
)
_OVERVIEW_ASK = "2. Ask me, e.g. “how many workers today?” or “cement stock?”"
_OVERVIEW_GET = "3. Get reports, e.g. “today's summary” or “send yesterday's report”"
_OVERVIEW_OUTRO = "Type it or send a voice note. Or pick what you're reporting:"

#: Variants for smalltalk; picked by a stable hash of the message so the same
#: text always gets the same line but different messages don't all get one.
_SMALLTALK_REPLIES = (
    "I'm Mesiri's site assistant. I'm best at site work. Try “how many workers today?” or tell me today's update.",
    "Fair point! I'm built for site work. Tell me what happened today, or ask me something like “cement stock?”.",
    "I'll keep it simple: send me today's site update, or ask “send yesterday's report”. I'm happy to help with that.",
    "Sorry if that sounded stiff. I'm a site assistant: tell me what got done today, or ask “today's summary”.",
)


def _pick_smalltalk(question: object) -> str:
    import hashlib

    text = question.strip().lower() if isinstance(question, str) else ""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return _SMALLTALK_REPLIES[digest[0] % len(_SMALLTALK_REPLIES)]


def _render_capability_overview(role: str | None) -> ReplySpec:
    """The answer to "what can you do?" -- an actual answer, then the menu.

    Role-filtered, so an engineer is told what *they* can do rather than
    what the product can do for somebody else.
    """
    from workflows.registry import iter_menu_categories

    # WA-11: short, friendly and with one example to copy -- a supervisor
    # asking "what is this?" needs to know what to send, not a feature list.
    # No module names here: the old list said "money" to companies with
    # finance switched off. The menu below is already filtered to the
    # company's switched-on modules (WA-07).
    return ReplySpec(
        text=(
            f"{_OVERVIEW_INTRO}\n"
            f"{_OVERVIEW_TELL}\n"
            f"{_OVERVIEW_ASK}\n"
            f"{_OVERVIEW_GET}\n\n"
            f"{_OVERVIEW_OUTRO}"
        ),
        list_button_label="Choose one",
        list_rows=tuple(
            ListRow(c.row_id, c.title, c.one_liner) for c in iter_menu_categories(role)
        ),
    )


def _visible_to_role(definition: WorkflowDefinition, role: str | None) -> bool:
    """Second role check, after capability_help.py's own filtered catalogue.

    Belt and braces on purpose: the matches travel through decision metadata,
    which is a plain dict that anything could have written, and the cost of
    re-checking is one set lookup against the registry.
    """
    if role is None or definition.allowed_roles is None:
        return True
    return role.upper() in definition.allowed_roles


def render_category_prompt(row_id: str) -> ReplySpec | None:
    """Resolve a tap on either level of the tiered menu. Deterministic -- no
    AI call, since we defined these row ids ourselves (see
    runtime/dependencies.py's category-tap fast path).

    Two levels, one function, because the caller dispatches both identically
    (see runtime/message_journey.py's category-tap branch -- it sends the
    ReplySpec and sets whatever hint the row carries, without caring which
    level produced it):

      * a category row  -> the list of workflows inside that category
      * a workflow row   -> that workflow's prompt and example messages

    Returns None for anything else: a stale/foreign button, a tampered
    payload, or -- importantly -- the material Arrived/Used ids, which are
    owned by handle_material_direction_tap further down the same chain and
    must fall through to it untouched.
    """
    from workflows.registry import (
        definition_by_menu_row_id,
        menu_category_by_row_id,
        user_initiable_in,
    )

    resolved_id = _LEGACY_CATEGORY_ROW_IDS.get(row_id, row_id)
    if resolved_id == "":
        # A legacy row whose workflow was never built. Say so rather than
        # silently reopening the menu, which reads as a dropped tap.
        return ReplySpec(
            text="That option isn't available any more. Here's what I can do:",
            list_button_label="Choose one",
            list_rows=CATEGORY_ROWS,
        )

    category = menu_category_by_row_id(resolved_id)
    if category is not None:
        rows = tuple(
            ListRow(d.menu_row_id, d.title, d.one_liner)
            for d in user_initiable_in(category.category)
        )
        return ReplySpec(
            text=f"*{category.title}* — what would you like to do?",
            list_button_label="Choose one",
            list_rows=rows,
        )

    definition = definition_by_menu_row_id(resolved_id)
    if definition is None or definition.menu_row_id_override:
        return None
    return ReplySpec(text=_render_workflow_prompt(definition))


def _render_workflow_prompt(definition: WorkflowDefinition) -> str:
    """The prompt shown once a specific workflow is picked from the menu:
    what it does, and how to phrase it. Examples come from the registry, so
    what the menu teaches and what the control panel documents are the same
    strings."""
    examples = "\n".join(f'  • "{e}"' for e in definition.examples)
    return f"*{definition.title}* — {definition.one_liner}.\n\nFor example:\n{examples}"


def render_understanding_failed_reply() -> str:
    """The AI could not make sense of the message at all (UNUSABLE confidence)."""
    return (
        "Sorry, I couldn't make out that message. Could you send it again — "
        "typed, or as a clearer voice note?"
    )


# How each switchable module is named to a WhatsApp user (WA-07). The keys
# are backend domains/organizations/settings.py's MODULES.
_MODULE_USER_NAMES: dict[str, tuple[str, str]] = {
    "dpr": ("Daily progress reports", "them"),
    "labour": ("Labour attendance", "it"),
    "materials": ("Materials", "it"),
    "finance": ("Expenses", "them"),
    "automations": ("Scheduled messages", "them"),
}

#: Present in every module-disabled reply; lets callers recognise one.
MODULE_DISABLED_MARKER = "switched on for your company"


def is_module_disabled_reply(text: str) -> bool:
    return MODULE_DISABLED_MARKER in text


#: Roles that run the company: there is no admin above them to ask. Modules
#: are switched on by the Mesiri team (control panel), not on the dashboard.
_COMPANY_ADMIN_ROLES = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN"})


def render_module_disabled_reply(module: str, role: str | None = None) -> str:
    """A request for a module the company hasn't switched on (WA-07).

    One short line, no menu (request [59]): it says plainly that the module is
    off for the company -- not that the user typed something wrong. An admin
    is not told to ask their admin (round 3, 21 Oct).
    """
    name, pronoun = _MODULE_USER_NAMES.get(module, (module.capitalize(), "it"))
    verb = "aren't" if pronoun == "them" else "isn't"
    who = "the Mesiri team" if str(role or "").strip().upper() in _COMPANY_ADMIN_ROLES else "your admin"
    return (
        f"{name} {verb} {MODULE_DISABLED_MARKER} yet, so I didn't record this. "
        f"Ask {who} to turn {pronoun} on."
    )


def render_unsupported_reply() -> str:
    """The intent was understood but no workflow exists for it yet.

    Distinct from ``render_understanding_failed_reply``: telling someone who
    reported an expense that we "couldn't make out" their message sends them
    rephrasing a message that was never the problem.

    Generated from workflows/registry.py rather than written down. The
    hand-written version of this string said "I can only record material
    updates right now" and was still saying it long after finance, labour,
    progress, and project workflows shipped -- a reply whose entire job is
    to state the system's limits is the worst possible place for copy that
    can silently fall out of date.
    """
    from workflows.registry import iter_menu_categories

    lines = "\n".join(f"  • {c.title} — {c.one_liner.lower()}" for c in iter_menu_categories())
    return (
        "I understood that, but I can't do that one yet.\n\n"
        f"Here's what I can help with:\n{lines}\n\n"
        'Send "menu" to pick from the list.'
    )
