"""V1 audit SIT-01: a site the message names that is none of the sender's
sites is asked about, never saved under today's site."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ports import SiteSummary
from runtime.agent.entry_base import EntryScope
from runtime.agent.tools import ScopeLookup, to_candidate

A1, B1, B2 = SiteSummary("a1", "Site A", "pa"), SiteSummary("b1", "Site A", "pb"), SiteSummary("b2", "Site B", "pb")
SCOPE = ScopeLookup(
    projects=(("pa", "Project A"), ("pb", "Project B")),
    sites=(("a1", "Site A", "pa"), ("b2", "Site B", "pb")),
)


class _Entry(EntryScope):
    __slots__ = ("actor",)


def _entry(*sites):
    entry = _Entry()
    entry.actor = SimpleNamespace(sites=list(sites))
    return entry


@pytest.mark.parametrize("said", ["Site Z", "Sight B", "Tower 9"])
def test_a_named_site_that_matches_none_is_asked(said):
    candidate = to_candidate("save_labour", {"workers": [{"trade": "mason", "headcount": 5}], "site": said}, SCOPE)
    assert candidate.fields.get("site_name") == said
    # The context layer fell back to today's site (b2).
    say = _entry(A1, B2)._unmatched_site(candidate, "pb", "b2")
    assert say is not None and say.status == "choose"
    assert say.question == f'I don\'t have a site called "{said}". Which site is this for?'
    assert say.options == ("Site B",)  # this project's sites


def test_a_project_with_none_of_their_sites_offers_all_of_them():
    candidate = SimpleNamespace(fields={"site_name": "Site Z"})
    say = _entry(A1, B2)._unmatched_site(candidate, "pz", None)
    assert say.options == ("Site A", "Site B")


def test_a_matched_or_unnamed_site_goes_on():
    entry = _entry(A1, B1, B2)
    # Matched to an id: not this check's business.
    assert entry._unmatched_site(SimpleNamespace(fields={"site_id": "b2"}), "pb", "b2") is None
    # Nothing named: today's site stands.
    assert entry._unmatched_site(SimpleNamespace(fields={}), "pb", "b2") is None
    # A name two projects share ("Site A") is settled by the project below.
    assert entry._unmatched_site(SimpleNamespace(fields={"site_name": "site a"}), "pb", None) is None
    assert entry._unmatched_site(SimpleNamespace(fields={"site_name": "Site A"}), "pb", "b1") is None
