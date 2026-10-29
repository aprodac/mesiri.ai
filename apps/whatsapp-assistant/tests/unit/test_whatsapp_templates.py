"""WA-12: template messages -- the registry's choice, the sender's payload
shape (pinned to the Cloud API reference: type="template", language.code,
header document + body text parameters), the out-of-window send policy in
runtime/send_pending_notifications.py, and the webhook's failed-status log."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

import mesiri.application.notifications.checks as checks
import runtime.notification_query as notification_query
from channel.whatsapp.outbound import WhatsAppSender
from channel.whatsapp.templates import (
    DPR_DELIVERY,
    LOGIN_CODE,
    SITE_DAY_REVIEW,
    approved_template_names,
    choose_template,
    clean_param,
)
from ingress.receiver import _log_failed_statuses
from runtime.send_pending_notifications import drain_and_send

APPROVED = frozenset({DPR_DELIVERY.name})
_REAL_IS_QUIET_HOURS = checks.is_quiet_hours


def _template_payload(params=("Tower A", "13 Oct 2026", "All sites reported.")):
    return {
        "message": "Today's DPR (DPR-P-1) is attached.",
        "document_object_key": "dpr/1/2.pdf",
        "template": {"name": DPR_DELIVERY.name, "body_params": list(params)},
    }


# --- registry ---------------------------------------------------------------


def test_approved_names_parse_the_comma_separated_setting():
    assert approved_template_names(" mesiri_dpr_delivery , other ,,") == {"mesiri_dpr_delivery", "other"}
    assert approved_template_names("") == frozenset()
    assert approved_template_names(None) == frozenset()


def test_params_are_single_line_collapsed_capped_and_never_empty():
    assert clean_param("Tower A\n\tBlock   2     ") == "Tower A Block 2"
    assert clean_param("") == "-"
    assert clean_param(None) == "-"
    assert len(clean_param("x" * 500)) == 200


def test_no_template_in_payload_keeps_the_old_skip_reason():
    choice = choose_template({"message": "hi"}, APPROVED)
    assert choice.spec is None
    assert choice.skip_reason == "outside_whatsapp_session_window_needs_template"


def test_a_template_not_yet_approved_is_skipped_with_its_name():
    choice = choose_template(_template_payload(), frozenset())
    assert choice.spec is None
    assert choice.skip_reason == "template_not_approved:mesiri_dpr_delivery"


def test_an_unknown_template_is_skipped():
    choice = choose_template({"template": {"name": "nope", "body_params": []}}, frozenset({"nope"}))
    assert choice.skip_reason == "unknown_template:nope"


def test_wrong_param_count_is_skipped_not_sent():
    choice = choose_template(_template_payload(params=("only one",)), APPROVED)
    assert choice.skip_reason == "template_params_mismatch:mesiri_dpr_delivery"


def test_an_approved_template_is_chosen_with_cleaned_params():
    choice = choose_template(_template_payload(params=("Tower\nA", "13 Oct 2026", "ok")), APPROVED)
    assert choice.spec is DPR_DELIVERY
    assert choice.body_params == ("Tower A", "13 Oct 2026", "ok")


def test_no_update_reminder_template_is_chosen_with_its_closed_tap():
    """WA-06: the reminder's template payload passes the shape checks."""
    import datetime as _dt

    from channel.whatsapp.templates import SITE_NO_UPDATE
    from runtime.site_day_review import no_update_payload

    payload = no_update_payload(
        site_id="s1",
        site_name="Block A",
        project_name="Green Towers",
        deadline="21:00",
        report_date=_dt.date(2026, 10, 16),
    )
    choice = choose_template(payload, frozenset({SITE_NO_UPDATE.name}))
    assert choice.spec is SITE_NO_UPDATE
    assert choice.body_params == ("Block A (Green Towers)", "9:00 pm")
    assert choice.button_payloads == ("sdr:closed:s1:20261016",)


# --- sender -----------------------------------------------------------------


def _sender(captured: list[httpx.Request], *, upload_status: int = 200) -> WhatsAppSender:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(upload_status, json={"id": "MEDIA_1"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.tpl.1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")


@pytest.mark.asyncio
async def test_send_template_payload_matches_cloud_api_shape():
    captured: list[httpx.Request] = []
    ok = await _sender(captured).send_template(
        "919999999999",
        name="mesiri_dpr_delivery",
        language="en",
        body_params=("Tower A", "13 Oct 2026", "All sites reported."),
        header_document=(b"%PDF", "DPR.pdf"),
    )
    assert ok is True
    assert captured[0].url.path.endswith("/PHONE_NUMBER_ID/media")
    body = json.loads(captured[1].content)
    assert body["to"] == "919999999999"
    assert body["type"] == "template"
    assert body["template"] == {
        "name": "mesiri_dpr_delivery",
        "language": {"code": "en"},
        "components": [
            {
                "type": "header",
                "parameters": [{"type": "document", "document": {"id": "MEDIA_1", "filename": "DPR.pdf"}}],
            },
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "Tower A"},
                    {"type": "text", "text": "13 Oct 2026"},
                    {"type": "text", "text": "All sites reported."},
                ],
            },
        ],
    }


@pytest.mark.asyncio
async def test_login_code_template_sends_the_code_to_body_and_copy_button():
    # SS-06: an authentication template takes the code twice -- body {{1}}
    # and the "Copy code" button's url parameter.
    captured: list[httpx.Request] = []
    ok = await _sender(captured).send_template(
        "919999999999",
        name=LOGIN_CODE.name,
        language=LOGIN_CODE.language,
        body_params=("482913",),
        button_url_param="482913",
    )
    assert ok is True
    assert json.loads(captured[0].content)["template"]["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "482913"}]},
        {
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": "482913"}],
        },
    ]


@pytest.mark.asyncio
async def test_send_template_without_params_or_header_has_no_components():
    captured: list[httpx.Request] = []
    assert await _sender(captured).send_template("91", name="hello", language="en") is True
    assert json.loads(captured[0].content)["template"] == {"name": "hello", "language": {"code": "en"}}


@pytest.mark.asyncio
async def test_send_template_does_not_send_when_the_document_upload_fails():
    captured: list[httpx.Request] = []
    ok = await _sender(captured, upload_status=500).send_template(
        "91", name="mesiri_dpr_delivery", language="en", header_document=(b"%PDF", "DPR.pdf")
    )
    assert ok is False
    assert len(captured) == 1  # the upload only; no message went out


# --- send policy ------------------------------------------------------------


class _FakeSender:
    def __init__(self):
        self.texts: list = []
        self.documents: list = []
        self.templates: list = []

    async def send_text(self, wa_id, body):
        self.texts.append((wa_id, body))
        return True

    async def send_document(self, wa_id, data, *, filename, mime_type, shows=None):
        self.documents.append((wa_id, filename))
        return True

    async def send_template(self, wa_id, **kwargs):
        self.templates.append((wa_id, kwargs))
        return True

    async def send_button(self, wa_id, *, body, buttons, shows=None):
        self.buttons = getattr(self, "buttons", [])
        self.buttons.append((wa_id, body, [(b.id, b.title) for b in buttons]))
        return True


class _Storage:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def get_object(self, key):
        if self.fail:
            raise RuntimeError("gone")
        return SimpleNamespace(data=b"%PDF")


@pytest.fixture
def queue(monkeypatch):
    state = {
        "rows": [],
        "last_inbound": None,
        "sent": [],
        "skipped": [],
        "consent": {},
        "timezone": "Asia/Kolkata",
        "timezone_lookups": [],
    }

    class _Queue:
        def __init__(self, db, actor_reader):
            pass

        async def list_pending(self):
            return state["rows"]

        async def resolve_recipient_wa_id(self, user_id):
            return "919999999999"

        async def consent_state(self, *, organization_id, wa_id):
            return state["consent"].get(wa_id)

        async def timezone_for(self, *, organization_id, project_id):
            state["timezone_lookups"].append((organization_id, project_id))
            return state["timezone"]

        async def last_inbound_at(self, wa_id):
            return state["last_inbound"]

        async def mark_sent(self, *, notification_id):
            state["sent"].append(notification_id)

        async def mark_skipped(self, *, notification_id, reason):
            state["skipped"].append((notification_id, reason))

    monkeypatch.setattr(notification_query, "NotificationSendQueueService", _Queue)
    monkeypatch.setattr(checks, "is_quiet_hours", lambda *, local_now: False)
    return state


def _row(payload, *, recipient_user_id="u1"):
    return {
        "id": "n1",
        "organization_id": "org1",
        "rule_key": "project_dpr_send:p1",
        "recipient_user_id": recipient_user_id,
        "payload": payload,
    }


async def _drain(sender, *, approved=APPROVED, storage=None, now_utc=None):
    return await drain_and_send(
        db=None,
        actor_reader=None,
        sender=sender,
        object_storage=storage or _Storage(),
        approved_templates=approved,
        now_utc=now_utc,
    )


@pytest.mark.asyncio
async def test_inside_the_window_the_free_form_send_is_unchanged(queue):
    queue["rows"] = [_row(_template_payload())]
    queue["last_inbound"] = datetime.now(tz=UTC) - timedelta(hours=1)
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert sender.texts == [("919999999999", "Today's DPR (DPR-P-1) is attached.")]
    assert sender.documents == [("919999999999", "DPR.pdf")]
    assert sender.templates == []


@pytest.mark.asyncio
async def test_outside_the_window_an_approved_template_is_sent_with_the_pdf(queue):
    queue["rows"] = [_row(_template_payload())]
    queue["last_inbound"] = datetime.now(tz=UTC) - timedelta(days=3)
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert sender.texts == []
    ((wa_id, kwargs),) = sender.templates
    assert wa_id == "919999999999"
    assert kwargs["name"] == "mesiri_dpr_delivery"
    assert kwargs["language"] == "en"
    assert kwargs["body_params"] == ("Tower A", "13 Oct 2026", "All sites reported.")
    assert kwargs["header_document"] == (b"%PDF", "DPR.pdf")
    assert queue["sent"] == ["n1"]


@pytest.mark.asyncio
async def test_a_recipient_who_never_messaged_also_gets_the_template(queue):
    queue["rows"] = [_row(_template_payload())]
    queue["last_inbound"] = None
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert len(sender.templates) == 1


@pytest.mark.asyncio
async def test_outside_the_window_without_approval_it_is_skipped_as_before(queue):
    queue["rows"] = [_row(_template_payload())]
    sender = _FakeSender()

    assert await _drain(sender, approved=frozenset()) == {"sent": 0, "skipped": 1}
    assert queue["skipped"] == [("n1", "template_not_approved:mesiri_dpr_delivery")]
    assert sender.templates == [] and sender.texts == []


@pytest.mark.asyncio
async def test_outside_the_window_a_row_with_no_template_keeps_the_old_reason(queue):
    queue["rows"] = [_row({"message": "Reminder"})]
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 0, "skipped": 1}
    assert queue["skipped"] == [("n1", "outside_whatsapp_session_window_needs_template")]


@pytest.mark.asyncio
async def test_a_document_template_with_an_unreadable_pdf_is_not_sent(queue):
    queue["rows"] = [_row(_template_payload())]
    sender = _FakeSender()

    assert await _drain(sender, storage=_Storage(fail=True)) == {"sent": 0, "skipped": 1}
    assert queue["skipped"] == [("n1", "send_failed")]
    assert sender.templates == []


# --- webhook ----------------------------------------------------------------


def test_failed_delivery_statuses_are_logged(caplog):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {"id": "wamid.ok", "status": "delivered", "recipient_id": "91"},
                                {
                                    "id": "wamid.tpl.1",
                                    "status": "failed",
                                    "recipient_id": "919999999999",
                                    "errors": [{"code": 132001, "title": "Template name does not exist"}],
                                },
                            ]
                        },
                    }
                ]
            }
        ]
    }
    with caplog.at_level(logging.WARNING):
        _log_failed_statuses(payload)
    failed = [r.getMessage() for r in caplog.records if "delivery_failed" in r.getMessage()]
    assert failed == [
        "whatsapp.delivery_failed wamid=wamid.tpl.1 to=919999999999 code=132001 "
        "title=Template name does not exist"
    ]


# --- BE-15: opt-in / opt-out at send time -------------------------------------


def _contact_payload():
    return {**_template_payload(), "to_wa_id": "447911123456", "requires_opt_in": True}


@pytest.mark.asyncio
async def test_a_contact_without_an_opt_in_is_skipped(queue):
    queue["rows"] = [_row(_contact_payload(), recipient_user_id=None)]
    queue["last_inbound"] = datetime.now(tz=UTC) - timedelta(hours=1)
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 0, "skipped": 1}
    assert queue["skipped"] == [("n1", "no_opt_in")]
    assert sender.texts == [] and sender.templates == []


@pytest.mark.asyncio
async def test_an_opted_in_contact_gets_the_dpr_at_their_own_number(queue):
    queue["rows"] = [_row(_contact_payload(), recipient_user_id=None)]
    queue["consent"] = {"447911123456": "opted_in"}
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    ((wa_id, _),) = sender.templates  # never messaged us, so the template
    assert wa_id == "447911123456"


@pytest.mark.asyncio
async def test_a_user_who_opted_out_is_skipped(queue):
    queue["rows"] = [_row(_template_payload())]
    queue["last_inbound"] = datetime.now(tz=UTC) - timedelta(hours=1)
    queue["consent"] = {"919999999999": "opted_out"}
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 0, "skipped": 1}
    assert queue["skipped"] == [("n1", "opted_out")]


@pytest.mark.asyncio
async def test_a_contact_row_with_no_number_is_skipped(queue):
    queue["rows"] = [_row({"requires_opt_in": True}, recipient_user_id=None)]
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 0, "skipped": 1}
    assert queue["skipped"] == [("n1", "no_resolvable_recipient")]


# --- BE-38: quiet hours in local time ---------------------------------------


@pytest.fixture
def quiet(queue, monkeypatch):
    """The `queue` fixture with the real quiet-hours check (21:00-07:00)."""
    monkeypatch.setattr(checks, "is_quiet_hours", _REAL_IS_QUIET_HOURS)
    return queue


def _nudge(n="n1", *, project_id=None):
    return {
        "id": n,
        "organization_id": "org1",
        "project_id": project_id,
        "rule_key": "stuck_confirmation",
        "recipient_user_id": "u1",
        "payload": {},
    }


async def _drain_at(state, now_utc):
    state["last_inbound"] = now_utc - timedelta(hours=1)
    sender = _FakeSender()
    return await _drain(sender, now_utc=now_utc), sender


@pytest.mark.asyncio
async def test_22_00_india_time_is_held_though_it_is_16_30_utc(quiet):
    quiet["rows"] = [_nudge()]
    counts, sender = await _drain_at(quiet, datetime(2026, 10, 14, 16, 30, tzinfo=UTC))

    assert counts == {"sent": 0, "skipped": 0}
    assert sender.texts == [] and quiet["skipped"] == []  # left pending


@pytest.mark.asyncio
async def test_04_30_india_time_is_held_though_it_is_23_00_utc(quiet):
    quiet["rows"] = [_nudge()]
    counts, sender = await _drain_at(quiet, datetime(2026, 10, 14, 23, 0, tzinfo=UTC))

    assert counts == {"sent": 0, "skipped": 0}
    assert sender.texts == []


@pytest.mark.asyncio
async def test_10_00_india_time_is_sent_though_it_is_04_30_utc(quiet):
    quiet["rows"] = [_nudge()]
    counts, sender = await _drain_at(quiet, datetime(2026, 10, 14, 4, 30, tzinfo=UTC))

    assert counts == {"sent": 1, "skipped": 0}
    assert len(sender.texts) == 1


@pytest.mark.asyncio
async def test_an_unknown_timezone_name_falls_back_to_utc_instead_of_crashing(quiet):
    quiet["timezone"] = "Not/AZone"
    quiet["rows"] = [_nudge()]
    counts, _ = await _drain_at(quiet, datetime(2026, 10, 14, 12, 0, tzinfo=UTC))

    assert counts == {"sent": 1, "skipped": 0}


@pytest.mark.asyncio
async def test_the_project_dpr_at_its_21_00_deadline_is_not_held(quiet):
    quiet["rows"] = [_row(_template_payload())]  # project_dpr_send:p1
    counts, sender = await _drain_at(quiet, datetime(2026, 10, 14, 15, 35, tzinfo=UTC))

    assert counts == {"sent": 1, "skipped": 0}
    assert sender.documents == [("919999999999", "DPR.pdf")]
    assert quiet["timezone_lookups"] == []


@pytest.mark.asyncio
async def test_a_nudge_at_21_05_india_time_is_still_held(quiet):
    quiet["rows"] = [_nudge()]
    counts, _ = await _drain_at(quiet, datetime(2026, 10, 14, 15, 35, tzinfo=UTC))

    assert counts == {"sent": 0, "skipped": 0}


@pytest.mark.asyncio
async def test_the_timezone_is_looked_up_once_per_project(quiet):
    quiet["rows"] = [_nudge("n1", project_id="p1"), _nudge("n2", project_id="p1")]
    counts, _ = await _drain_at(quiet, datetime(2026, 10, 14, 4, 30, tzinfo=UTC))

    assert counts == {"sent": 2, "skipped": 0}
    assert quiet["timezone_lookups"] == [("org1", "p1")]


def test_the_project_timezone_wins_over_the_company_timezone():
    assert (
        notification_query.pick_notification_timezone(
            project_timezone="Asia/Dubai", org_timezone="Asia/Kolkata"
        )
        == "Asia/Dubai"
    )


def test_utc_counts_as_not_set_and_falls_through():
    pick = notification_query.pick_notification_timezone
    assert pick(project_timezone="UTC", org_timezone="Asia/Dubai") == "Asia/Dubai"
    assert pick(project_timezone="UTC", org_timezone="UTC") == "Asia/Kolkata"
    assert pick(project_timezone=None, org_timezone=None) == "Asia/Kolkata"


# --- WA-04: quick replies, buttons, the evening review's send time ----------------


def _review_payload(button_payloads=("sdr:open:s1:20261015",)):
    return {
        "message": "Block A is missing the labour count.",
        "buttons": [{"id": "sdr:closed:s1:20261015", "title": "Site closed today"}],
        "template": {
            "name": SITE_DAY_REVIEW.name,
            "body_params": ["Block A", "Labour count is missing.", "9:00 pm"],
            "button_payloads": list(button_payloads),
        },
    }


def test_a_quick_reply_template_needs_a_payload_per_button():
    approved = frozenset({SITE_DAY_REVIEW.name})
    assert choose_template(_review_payload(button_payloads=()), approved).skip_reason == (
        "template_buttons_mismatch:mesiri_site_day_review"
    )
    choice = choose_template(_review_payload(), approved)
    assert choice.spec is SITE_DAY_REVIEW
    assert choice.button_payloads == ("sdr:open:s1:20261015",)


def test_a_template_without_buttons_must_not_be_given_payloads():
    payload = _template_payload()
    payload["template"]["button_payloads"] = ["x"]
    assert choose_template(payload, APPROVED).skip_reason == "template_buttons_mismatch:mesiri_dpr_delivery"


@pytest.mark.asyncio
async def test_quick_reply_payloads_follow_the_cloud_api_shape():
    captured: list[httpx.Request] = []
    assert await _sender(captured).send_template(
        "91",
        name=SITE_DAY_REVIEW.name,
        language="en",
        body_params=("Block A", "Labour count is missing.", "9:00 pm"),
        quick_reply_payloads=("sdr:open:s1:20261015",),
    )
    assert json.loads(captured[0].content)["template"]["components"][-1] == {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": "sdr:open:s1:20261015"}],
    }


def _review_row(payload):
    return {**_row(payload), "rule_key": "site_day_gap:s1", "project_id": "p1"}


@pytest.mark.asyncio
async def test_inside_the_window_a_row_with_buttons_is_sent_with_them(queue):
    queue["rows"] = [_review_row(_review_payload())]
    queue["last_inbound"] = datetime.now(tz=UTC) - timedelta(hours=1)
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert sender.texts == []
    assert sender.buttons == [
        (
            "919999999999",
            "Block A is missing the labour count.",
            [("sdr:closed:s1:20261015", "Site closed today")],
        )
    ]


@pytest.mark.asyncio
async def test_outside_the_window_the_review_goes_as_its_template_with_the_tap(queue):
    queue["rows"] = [_review_row(_review_payload())]
    sender = _FakeSender()

    assert await _drain(sender, approved=frozenset({SITE_DAY_REVIEW.name})) == {"sent": 1, "skipped": 0}
    ((_, kwargs),) = sender.templates
    assert kwargs["name"] == "mesiri_site_day_review"
    assert kwargs["quick_reply_payloads"] == ("sdr:open:s1:20261015",)
    assert kwargs["header_document"] is None


@pytest.mark.asyncio
async def test_the_evening_review_is_not_held_by_quiet_hours(queue, monkeypatch):
    monkeypatch.setattr(checks, "is_quiet_hours", lambda *, local_now: True)
    queue["rows"] = [
        _review_row(_review_payload()),
        {**_row({"message": "x"}), "id": "n2", "rule_key": "stuck_confirmation"},
    ]
    queue["last_inbound"] = datetime.now(tz=UTC) - timedelta(hours=1)
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert queue["sent"] == ["n1"]  # the other row waits for the morning


@pytest.mark.asyncio
async def test_a_post_into_a_site_group_skips_the_per_person_checks(queue):
    """WA-87: the evening DPR into a site's WhatsApp group: no opt-in or 24 h
    window of a person applies, so it goes as the free-form message + PDF."""
    queue["rows"] = [_row({**_template_payload(), "to_wa_id": "group:120363000000000001"}, recipient_user_id=None)]
    queue["last_inbound"] = None  # would be "outside the window" for a person
    sender = _FakeSender()

    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert sender.templates == []
    assert sender.texts[0][0] == "group:120363000000000001"
