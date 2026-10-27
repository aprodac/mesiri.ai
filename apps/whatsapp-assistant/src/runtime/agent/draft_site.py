"""The site of a draft item: one resolver (request 132, P2.5).

With a company's ``draft_v2`` setting on, an item's site is decided in one order
and nowhere else:

1. the sender has one site -> that site;
2. the message names one of their sites (whole words, the matcher the site
   question uses: ``site_match.find_sites``), "Green Villa ground floor wall
   putty 200 sqft" included, whether or not the model passed a site name;
3. the site of their last SAVED site update, for ``work_site.SAVE_WINDOW_SECONDS``
   (the preselection of request 129);
4. otherwise they are asked.

Steps 1 and 3 are the entry's (``entry_base.EntryScope``); this module is step 2
and the rule for what may ever write site context: only a save writes it, and
"now at Site B" (a plain statement of where they are) preselects for the same
window. A site named while setting up the team ("Site B-il Rajesh-ine supervisor
aakku"), asking a question or creating a site says where something IS, so it
writes nothing -- it used to pin Site B for the whole day.

Pure functions; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import site_match

SINGLE = "single"
NAMED = "named"
SAVED = "saved"
ASK = "ask"

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


def _sites(actor: Any) -> list[Any]:
    return [s for s in getattr(actor, "sites", None) or [] if getattr(s, "id", None)]


def _projects(actor: Any) -> dict[str, str]:
    return {str(p.id): p.name for p in getattr(actor, "projects", None) or []}


def named_in(actor: Any, text: str) -> Any | None:
    """The one site of the sender that ``text`` names, else None (nothing named,
    or more than one: then the question stands)."""
    hits = site_match.find_sites(_sites(actor), text, _projects(actor), part=False)
    return hits[0] if len(hits) == 1 else None


def resolve(actor: Any, text: str, *, saved_site_id: str | None = None) -> SiteChoice:
    """The site for an item of a message, in the one order (see the module)."""
    sites = _sites(actor)
    if len(sites) == 1:
        return SiteChoice(SINGLE, sites[0])
    if (named := named_in(actor, text)) is not None:
        return SiteChoice(NAMED, named)
    if saved_site_id:
        saved = next((s for s in sites if str(s.id) == str(saved_site_id)), None)
        if saved is not None:
            return SiteChoice(SAVED, saved)
    return SiteChoice(ASK)


def with_named_site(actor: Any, candidate: Any, text: str) -> Any:
    """``candidate`` with the site its message names, when the model passed none:
    the entry then treats the site as named, so neither today's site nor the
    last save overrides what the sender wrote."""
    fields = dict(getattr(candidate, "fields", None) or {})
    if any(fields.get(key) for key in ("site_id", "site_name")):
        return candidate
    named = named_in(actor, text)
    if named is None:
        return candidate
    return candidate.model_copy(update={"fields": {**fields, "site_name": str(named.name)}})


def is_location_statement(actor: Any, text: str, site_name: str) -> bool:
    """Whether ``text`` only says where the sender is working ("now at Site B",
    "innu Green Villa site-il"): the site's name, little words and nothing else.
    "Site B-il Rajesh-ine supervisor aakku" is about someone else, not a move."""
    drop = set(site_match.words(site_name))
    rest = [w for w in site_match.words(text) if w not in drop and w not in _LOCATION_FILLER]
    return len(rest) <= _LOCATION_EXTRA and not any(ch.isdigit() for word in rest for ch in word)
