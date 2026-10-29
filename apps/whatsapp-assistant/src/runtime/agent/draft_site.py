"""The site of a draft item: THE resolver (request 132, wired in by request 136).

With a company's ``draft_v2`` setting on, an item's site is decided here, in one
order, and nowhere else (``draft_flow.add`` calls ``resolve`` before the entry runs
and hands the entry the site it decided; the entry's own today's-site / context-layer
fallback never sees a draft item without a site):

1. the sender has one site -> that site;
2. the message (or the site name the model passed) names one of their sites:
   whole words, the site's full name or its head ("Green Villa" of "Green Villa,
   Kakkanad": ``site_match.mentioned_sites``); two or more -> asked among them;
   a name that is none of theirs -> asked among all;
3. the open card is for one site -> that site (WA-81);
4. the site of their last SAVED site update, for ``work_site.SAVE_WINDOW_SECONDS``
   (the preselection of request 129, or "now at Site B");
5. otherwise they are asked.

The readers of day figures use the same order without the question and the card
(``ASK`` then means every site of the project: ``JourneyGateway._reading_site``).

This module is also the rule for what may ever write site context: only a save
writes it, and "now at Site B" (a plain statement of where they are) preselects for
the same window. A site named while setting up the team ("Site B-il Rajesh-ine
supervisor aakku"), asking a question or creating a site says where something IS,
so it writes nothing -- it used to pin Site B for the whole day.

Pure functions; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import site_match

SINGLE = "single"
NAMED = "named"
CARD = "card"
SAVED = "saved"
ASK = "ask"
#: Request 136 (C): who decided a draft item's site, as the turn's trace records it.
DECIDER = "draft_site.resolve"

#: Words around a site name in a statement of where the sender is ("now at Site
#: B", "innu Green Villa site-il", "aaj Green Villa mein"): more than a few
#: others is a sentence about something else.
_LOCATION_FILLER = frozenset(
    {
        "at", "in", "now", "today", "am", "i", "im", "i'm", "the", "to", "is", "working", "work", "site",
        "innu", "ippo", "inn", "il", "ilaanu", "aanu", "und", "njan", "ninn", "aaj", "abhi", "mein", "main",
        "par", "pe", "hoon", "hu", "hun", "ahe", "illa",
    }
)
#: The most words that are neither the site's name nor filler.
_LOCATION_EXTRA = 1


@dataclass(frozen=True, slots=True)
class SiteChoice:
    kind: str
    site: Any | None = None
    #: ``ASK`` only: the sites to choose from (those the message names when it names
    #: several, else all of the sender's), and the name said that is none of theirs.
    options: tuple[Any, ...] = field(default_factory=tuple)
    unknown: str = ""


def _sites(actor: Any) -> list[Any]:
    return [s for s in getattr(actor, "sites", None) or [] if getattr(s, "id", None)]


def _projects(actor: Any) -> dict[str, str]:
    return {str(p.id): p.name for p in getattr(actor, "projects", None) or []}


def named_sites(actor: Any, text: str, said: str = "") -> list[Any]:
    """The sender's sites named by the site name the model passed (``said``: a whole
    name or a whole-word part of one, "Green Villa" / "Tower") or else by the
    message (its full name or head in a row: ``site_match.mentioned_sites``)."""
    sites = _sites(actor)
    said = " ".join(str(said or "").split())
    if said:
        hits = site_match.find_sites(sites, said, _projects(actor), part=True) or site_match.mentioned_sites(
            sites, said
        )
        if hits:
            return hits
    return site_match.mentioned_sites(sites, text)


def named_in(actor: Any, text: str) -> Any | None:
    """The one site of the sender that ``text`` names, else None (nothing named,
    or more than one: then the question stands)."""
    hits = named_sites(actor, text)
    return hits[0] if len(hits) == 1 else None


def resolve(
    actor: Any,
    text: str,
    *,
    said: str = "",
    project_id: str | None = None,
    card_site_id: str | None = None,
    saved_site_id: str | None = None,
) -> SiteChoice:
    """The site for an item of a message, in the one order (see the module).
    ``project_id``: the project the model named, which narrows the sites."""
    sites = _sites(actor)
    if project_id:
        sites = [s for s in sites if str(s.project_id) == str(project_id)] or sites
    if len(sites) == 1:
        return SiteChoice(SINGLE, sites[0])
    own = {str(s.id) for s in sites}
    hits = [s for s in named_sites(actor, text, said) if str(s.id) in own]
    if len(hits) == 1:
        return SiteChoice(NAMED, hits[0])
    if hits:
        return SiteChoice(ASK, options=tuple(hits))
    said = " ".join(str(said or "").split())
    if said:
        # A name that is none of theirs: asked among all of them, never a fallback.
        return SiteChoice(ASK, options=tuple(sites), unknown=said)
    for kind, site_id in ((CARD, card_site_id), (SAVED, saved_site_id)):
        if site_id and (site := next((s for s in sites if str(s.id) == str(site_id)), None)) is not None:
            return SiteChoice(kind, site)
    return SiteChoice(ASK, options=tuple(sites))


def label(actor: Any, site: Any) -> str:
    """The site as one of the options reads ("Site A · Project B" when two of the
    sender's sites share its name), which the tools turn back into its id."""
    for known, text in site_match.labelled(_sites(actor), _projects(actor)):
        if str(known.id) == str(site.id):
            return text
    return str(site.name)


def is_location_statement(actor: Any, text: str, site_name: str) -> bool:
    """Whether ``text`` only says where the sender is working ("now at Site B",
    "innu Green Villa site-il"): the site's name, little words and nothing else.
    "Site B-il Rajesh-ine supervisor aakku" is about someone else, not a move."""
    drop = set(site_match.words(site_name))
    rest = [w for w in site_match.words(text) if w not in drop and w not in _LOCATION_FILLER]
    return len(rest) <= _LOCATION_EXTRA and not any(ch.isdigit() for word in rest for ch in word)
