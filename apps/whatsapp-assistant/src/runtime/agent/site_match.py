"""Which of the sender's sites a name means (V1 audit, SIT-01/06/09/13).

One strict rule for every place that turns words into a site: a name counts
only as whole words ("main" is not in "maintenance"; "Site" alone is every
site, so it asks). A near miss ("Sight B") is never taken as a match; it is
only used to put the closest sites first in the list they pick from. Nothing
here guesses: no match, or more than one, means the sender is asked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from typing import Any

#: Between a site and its project when two projects share the site name.
JOIN = " · "
#: "Something else" row: they type the name instead (same as materials, [103]).
SOMETHING_ELSE = "Something else"
#: A WhatsApp list holds ten rows: nine sites and "Something else".
LIST_SITES = 9
#: A near miss is only a hint for the order of the list, never a pick.
SIMILAR_AT_LEAST = 0.6

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def words(text: object) -> list[str]:
    """Lower-case whole words of ``text`` (punctuation and spacing ignored)."""
    return _WORD.findall(str(text or "").casefold())


def _has_run(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    n = len(needle)
    return n > 0 and any(list(haystack[i : i + n]) == list(needle) for i in range(len(haystack) - n + 1))


def name_matches(site_name: str, said: str, *, part: bool = True) -> bool:
    """Whether ``said`` names ``site_name``: the same words in a row (the site
    inside a longer sentence), or, with ``part``, what was said is a
    whole-word part of the name ("Tower" for "Tower 1 North")."""
    site_words, said_words = words(site_name), words(said)
    if len(" ".join(site_words)) < 3 or not said_words:
        return False
    return _has_run(said_words, site_words) or (part and _has_run(site_words, said_words))


def similarity(site_name: str, said: str) -> float:
    return SequenceMatcher(None, " ".join(words(site_name)), " ".join(words(said))).ratio()


def find_sites(
    sites: Iterable[Any], said: str, projects: dict[str, str] | None = None, *, part: bool = True
) -> list[Any]:
    """The sender's sites ``said`` names, whole words only. "Site A · Project B"
    (the list's own label for a name two projects share) picks that one."""
    sites = list(sites)
    text = " ".join(str(said or "").split())
    if not text:
        return []
    if JOIN.strip() in text:
        site_part, _, project_part = text.rpartition(JOIN.strip())
        exact = [
            s
            for s in sites
            if words(s.name) == words(site_part)
            and words((projects or {}).get(str(getattr(s, "project_id", "") or ""), "")) == words(project_part)
        ]
        if exact:
            return exact
    whole = [s for s in sites if words(s.name) == words(text)]
    if whole:
        return whole
    return [s for s in sites if name_matches(s.name, text, part=part)]


#: Request 136: what a site's name may be cut to in a sentence: the part before
#: the first of these ("Green Villa" of "Green Villa, Kakkanad").
_HEAD_END = re.compile(r",|\(|\s[-–·]\s|\s/\s")
#: A head made only of these words names no one site ("Site" of "Site, Block A").
_GENERIC = frozenset({"site", "sites", "project", "block", "tower", "phase", "the", "new", "old", "main"})


def head_words(site_name: str) -> list[str]:
    """The words a sentence may name the site by when it leaves the rest out: the
    name before its first comma, bracket or " - " ("Green Villa" for "Green Villa,
    Kakkanad"). Empty when there is no such cut or it is only generic words."""
    head = _HEAD_END.split(str(site_name or ""), maxsplit=1)[0]
    cut = words(head)
    if not cut or cut == words(site_name) or len(" ".join(cut)) < 3 or set(cut) <= _GENERIC:
        return []
    return cut


def mentioned_sites(sites: Iterable[Any], text: str) -> list[Any]:
    """Request 136: the sender's sites a whole sentence names, whole words only: the
    site's full name in a row, or its head ("Green Villa ground floor wall putty 200
    sqft" names "Green Villa, Kakkanad"). Several hits are for the sender to choose
    from, never guessed between. A head that is part of a full name said is that
    site's ("Green Villa, Aluva" said does not also name "Green Villa, Kakkanad")."""
    said = words(text)
    if not said:
        return []
    sites = list(sites)
    full = [s for s in sites if len(" ".join(words(s.name))) >= 3 and _has_run(said, words(s.name))]
    by_head = [
        s
        for s in sites
        if s not in full
        and (head := head_words(s.name))
        and _has_run(said, head)
        and not any(_has_run(words(f.name), head) for f in full)
    ]
    return full + by_head


def names_a_site(sites: Iterable[Any], text: str) -> bool:
    """The message names at least one of the sender's sites (whole words)."""
    return bool(find_sites(sites, text, part=False))


def labelled(sites: Sequence[Any], projects: dict[str, str]) -> list[tuple[Any, str]]:
    """``(site, label)``: the name, or "Site A · Project B" when two of the
    sender's sites share it, so no two options read the same."""
    counts: dict[tuple[str, ...], int] = {}
    for site in sites:
        key = tuple(words(site.name))
        counts[key] = counts.get(key, 0) + 1
    out = []
    for site in sites:
        project = projects.get(str(getattr(site, "project_id", "") or ""), "")
        shared = counts[tuple(words(site.name))] > 1
        out.append((site, f"{site.name}{JOIN}{project}" if shared and project else str(site.name)))
    return out


def closest(sites: Sequence[Any], said: str = "", first_id: str = "") -> list[Any]:
    """The sites in the order to offer them: the one used last time, then those
    most like what was said, then by name."""
    return sorted(
        sites,
        key=lambda s: (
            str(s.id) != first_id,
            -(similarity(s.name, said) if said and similarity(s.name, said) >= SIMILAR_AT_LEAST else 0.0),
            str(s.name).casefold(),
        ),
    )


def options(
    sites: Sequence[Any], projects: dict[str, str], said: str = "", first_id: str = ""
) -> tuple[list[str], bool]:
    """Labels to offer (at most nine and "Something else" past ten sites) and
    whether the list was cut."""
    ordered = closest(sites, said, first_id)
    label_of = {id(s): label for s, label in labelled(ordered, projects)}
    cut = len(ordered) > 10
    shown = ordered[:LIST_SITES] if cut else ordered
    names = [label_of[id(s)] for s in shown]
    return (names + [SOMETHING_ELSE] if cut else names), cut


def short_title(label: str, limit: int) -> str:
    """``label`` as a button or row title of at most ``limit`` characters,
    never cut inside a word: "Green Villa, Kakkanad" whole when it fits; a
    "Name · Project" label keeps its name and shortens the project (whole
    words, then initials); anything else drops trailing words and ends in "…".
    The full label goes in the row description."""
    label = " ".join(str(label).split())
    if len(label) <= limit:
        return label
    name, joined, project = label.rpartition(JOIN)[0], JOIN, label.rpartition(JOIN)[2]
    if name and len(name) + len(joined) + 1 <= limit:
        project_words = project.split()
        for n in range(len(project_words) - 1, 0, -1):
            tight = f"{name}{joined}{' '.join(project_words[:n])}…"
            if len(tight) <= limit:
                return tight
        initials = f"{name}{joined}{''.join(w[0] for w in project_words).upper()}"
        if len(initials) <= limit:
            return initials
    base = name or label
    kept: list[str] = []
    for word in base.split():
        if len(" ".join([*kept, word])) + 1 > limit:
            break
        kept.append(word)
    if kept:
        return " ".join(kept).rstrip(",;:-") + "…"
    return base[: limit - 1] + "…"  # one word longer than the limit: nothing else to keep
