"""request_dpr: the day's report as a PDF, made and sent by code (request 143).

"Send me today's report" used to run a workflow whose answer was a status line
("Today's report is made this evening. So far today: ...") that the model then
retold. A message like "innathe report ayakku" came back as "Today's report ready
aayittilla, ithu oru draft aanu" with no content and no PDF: the model kept the
status and dropped the day.

Here the report is always a document, from Day Facts:

- the day is the project's (its zone): today, or the day the sender named;
- the site is the one they named or work at; with several and none named, one
  PDF per site that has anything saved that day;
- per site: the confirmed DPR when the day is signed off (the site's, else the
  project's, which holds every site), otherwise the day as it stands now
  (``DayFacts.site_day``: work with its percents and amounts, labour, materials,
  issues) printed by the DPR template as a draft;
- the one sentence that goes with it is the code's, in the sender's language
  (``wording``). The model writes no report text.

Read-only: nothing is stored or confirmed. The PDFs are sent right after the tool
call, before the reply, as the old delivery step did.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from canonicalization.occurred_date import parse_stated_date
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.registry import module_for_event

from .entry_base import ALL_SITES, EntryScope, Say
from .project_day import project_today, project_zone_name
from .wording import day_words, language_of, say

_log = logging.getLogger("mesiri.agent")

#: More sites than this in one ask is a company-wide request: the first ones go,
#: the sentence names them.
MAX_SITE_REPORTS = 5


@dataclass(frozen=True, slots=True)
class ReportDoc:
    """One PDF to send: stored (``object_key``) or printed now (``data``)."""

    site_name: str
    filename: str
    confirmed: bool
    object_key: str | None = None
    data: bytes | None = None


@dataclass(slots=True)
class ReportEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    active_context: Any | None = None
    #: The turn's Day Facts (``runtime.day_facts.DayFacts``).
    day_facts: Any | None = None
    #: ``find_report``: a stored DPR's status and PDF (``DprRequestQueryService``).
    dpr_request_query: Any | None = None
    object_storage: Any | None = None
    #: The database, for the letterhead of a draft.
    db: Any | None = None
    #: ``(wa_id, data, *, filename, caption) -> bool``.
    send_document: Callable[..., Awaitable[Any]] | None = None
    renderer: Any | None = None
    #: What the last ask sent (for tests and the turn's log).
    sent: list[ReportDoc] = field(default_factory=list)

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Say | None:
        if getattr(candidate, "semantic_type", None) is not SemanticType.DPR_REQUEST:
            return None
        fields = {**candidate.fields, **candidate.unknown_fields}
        language = language_of(getattr(message, "text", "") or "")
        scoped = await self.settle(
            message,
            understanding,
            candidate,
            module=module_for_event(WorkflowKey.DPR_REQUEST, fields),
            ask_site=False,
            lookup=True,
        )
        if isinstance(scoped, Say):
            return scoped
        zone = project_zone_name(scoped.ctx.timezone)
        today = project_today(zone)
        stated = fields.get("report_date") or fields.get("occurred_on")
        day = parse_stated_date(stated, today=today) if stated not in (None, "") else today
        if day is None:
            return Say("answer", say("report.bad_date", language))
        words = day_words(day, today, language)
        sites = self._sites(scoped, all_sites=bool(fields.get(ALL_SITES)))
        try:
            docs = await self._documents(scoped.organization_id, str(scoped.project_id), sites, day)
        except Exception:  # noqa: BLE001 -- said plainly, never a stack text
            _log.exception("report_entry.failed correlation_id=%s", message.correlation_id)
            return Say("answer", say("report.failed", language))
        one = sites[0][1] if len(sites) == 1 else ""
        if docs is None:
            return Say("answer", say("report.failed", language))
        if not docs:
            return Say("answer", say("report.nothing", language, at=_at(one), **words))
        sent = await self._send(docs, message)
        if not sent:
            return Say("answer", say("report.not_sent", language))
        self.sent = sent
        if len(sent) == 1:
            key = "report.confirmed" if sent[0].confirmed else "report.draft"
            return Say("answer", say(key, language, at=_at(sent[0].site_name), **words), documents=1)
        names = ", ".join(d.site_name for d in sent if d.site_name)
        return Say("answer", say("report.many", language, sites=names, **words), documents=len(sent))

    def _sites(self, scoped: Any, *, all_sites: bool) -> list[tuple[str, str]]:
        """(id, name) of the sites the report is for: the settled one, else the
        sender's sites in the project."""
        own = [
            s
            for s in getattr(self.actor, "sites", None) or []
            if str(getattr(s, "project_id", None)) == str(scoped.project_id) and getattr(s, "id", None)
        ]
        if scoped.site_id is not None and not all_sites:
            name = next((s.name for s in own if str(s.id) == str(scoped.site_id)), "")
            return [(str(scoped.site_id), str(name or ""))]
        return [(str(s.id), str(s.name or "")) for s in own]

    async def _documents(
        self, organization_id: str, project_id: str, sites: list[tuple[str, str]], day: Any
    ) -> list[ReportDoc] | None:
        """The PDFs for the sites with anything saved that day; None when a day
        with entries could not be printed at all."""
        docs: list[ReportDoc] = []
        project_pdf: ReportDoc | None = None
        project_checked = failed = False
        for site_id, site_name in sites:
            if len(docs) >= MAX_SITE_REPORTS:
                break
            stored = await self._confirmed(organization_id, project_id, site_id, day, site_name)
            if stored is not None:
                docs.append(stored)
                continue
            site_day = await self.day_facts.site_day(
                organization_id=organization_id, project_id=project_id, site_id=site_id, day=day
            )
            if site_day.empty:
                continue
            if not project_checked:
                project_checked = True
                project_pdf = await self._confirmed(organization_id, project_id, None, day, "")
                if project_pdf is not None:
                    # The project's confirmed DPR holds every site's day: sent once.
                    docs.append(project_pdf)
            if project_pdf is not None:
                continue
            draft = await self._draft(site_day, site_name or site_day.site_name, day)
            if draft is None:
                failed = True
                continue
            docs.append(draft)
        if not docs and failed:
            return None
        return docs

    async def _confirmed(
        self, organization_id: str, project_id: str, site_id: str | None, day: Any, site_name: str
    ) -> ReportDoc | None:
        """The stored DPR when the day is signed off and its PDF can be fetched."""
        if self.dpr_request_query is None:
            return None
        try:
            found = await self.dpr_request_query.find_report(
                organization_id=organization_id, project_id=project_id, site_id=site_id, report_date=day
            )
            if found.get("status") != "ready" or not found.get("confirmed"):
                return None
            if self.object_storage is not None:
                await self.object_storage.head_object(found["object_key"])
        except Exception:  # noqa: BLE001 -- the day's draft answers instead
            _log.warning("report_entry.stored_unavailable site=%s", site_id, exc_info=True)
            return None
        code = str(found.get("code") or "DPR")
        return ReportDoc(site_name, f"{_file_part(code)}.pdf", True, object_key=found["object_key"])

    async def _draft(self, site_day: Any, site_name: str, day: Any) -> ReportDoc | None:
        from channel.dpr_document.day_document import day_pdf

        letterhead = None
        if self.db is not None:
            try:
                from channel.dpr_document.letterhead import load_project_letterhead

                async with self.db.transaction() as conn:
                    letterhead = await load_project_letterhead(conn, self.object_storage, site_day.project_id)
            except Exception:  # noqa: BLE001 -- the plain header
                letterhead = None
        try:
            data = await day_pdf(
                site_day, object_storage=self.object_storage, letterhead=letterhead, renderer=self.renderer
            )
        except Exception:  # noqa: BLE001 -- said as "couldn't make the report"
            _log.warning("report_entry.render_failed site=%s", site_day.site_id, exc_info=True)
            return None
        name = f"Draft-DPR-{_file_part(site_name or 'site')}-{day:%Y%m%d}.pdf"
        return ReportDoc(site_name, name, False, data=data)

    async def _send(self, docs: list[ReportDoc], message: Any) -> list[ReportDoc]:
        """Each PDF, one retry each; the ones that went."""
        if self.send_document is None:
            return []
        from runtime.inbound_journey._shared import _send_with_one_retry

        went: list[ReportDoc] = []
        for doc in docs:

            async def _one(doc: ReportDoc = doc) -> None:
                data = doc.data
                if data is None:
                    data = (await self.object_storage.get_object(doc.object_key)).data
                sent = await self.send_document(
                    message.sender.wa_id, data, filename=doc.filename, caption=None, shows=f"Report PDF: {doc.filename}"
                )
                if sent is False:
                    raise RuntimeError("send_document returned False")

            if await _send_with_one_retry(_one, what="report_entry.document", correlation_id=message.correlation_id):
                went.append(doc)
        return went


def _at(site_name: str) -> str:
    return f" · {site_name}" if site_name else ""


def _file_part(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "DPR"
