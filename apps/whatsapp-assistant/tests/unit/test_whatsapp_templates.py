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
    approved_template_names,
    choose_template,
    clean_param,
)
from ingress.receiver import _log_failed_statuses
from runtime.send_pending_notifications import drain_and_send

APPROVED = frozenset({DPR_DELIVERY.name})


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

    async def send_document(self, wa_id, data, *, filename, mime_type):
        self.documents.append((wa_id, filename))
        return True

    async def send_template(self, wa_id, **kwargs):
        self.templates.append((wa_id, kwargs))
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
    state = {"rows": [], "last_inbound": None, "sent": [], "skipped": [], "consent": {}}

    class _Queue:
        def __init__(self, db, actor_reader):
            pass

        async def list_pending(self):
            return state["rows"]

        async def resolve_recipient_wa_id(self, user_id):
            return "919999999999"

        async def consent_state(self, *, organization_id, wa_id):
            return state["consent"].get(wa_id)

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


async def _drain(sender, *, approved=APPROVED, storage=None):
    return await drain_and_send(
        db=None,
        actor_reader=None,
        sender=sender,
        object_storage=storage or _Storage(),
        approved_templates=approved,
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
