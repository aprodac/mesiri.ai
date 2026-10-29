"""What an "open issue" is (request 127, P2): ONE rule for every place that
counts or lists them on WhatsApp -- the "open issues?" answer (the assistant's
activity search) and the day's report (the DPR assembly and its draft line).

They disagreed on 27 Oct: the draft said "1 open issue" while "open issues?"
listed 2, because the draft counted only the day's own issues and the two
queries filtered differently. Now an issue is open when:

- its status is open or being handled (``OPEN_STATUSES``, the dashboard's own
  open rule, request 104 D4);
- it is a site issue, not a "Question for your engineer" note that older
  versions saved as an issue;
- it is saved (WA-77): an issue whose Save was not tapped counts nowhere.

The day's report also counts the issues of earlier days still open on it
(BE-51); "open issues?" counts what is open now. On the current day the two
are the same set.
"""

from __future__ import annotations

from mesiri.application.dpr import fact_review

#: Open, or acknowledged ("being handled").
OPEN_STATUSES: tuple[str, ...] = ("OPEN", "ACKNOWLEDGED")
#: The prefix of the engineer-question notes saved as issues before request 104.
ENGINEER_QUESTION_PREFIX = "Question for your engineer:"


def is_open(status: object) -> bool:
    return str(status or "") in OPEN_STATUSES


def site_issue_sql(alias: str = "site_issues") -> str:
    """SQL true for a real site issue (not an old engineer-question note).
    ``alias`` is a table name or alias from code, never input."""
    return f"COALESCE({alias}.narrative, '') NOT LIKE '{ENGINEER_QUESTION_PREFIX}%'"


def counted_issue_sql(alias: str = "site_issues") -> str:
    """SQL true for an issue that is saved (WA-77)."""
    return fact_review.counted_sql(fact_review.SITE_ISSUE, f"{alias}.id")


def open_issue_sql(alias: str = "site_issues", *, counted: bool = True) -> str:
    """SQL true for an issue that is open now, by the rule above. ``counted``
    False keeps unsaved ones (the assistant's own picture of the day)."""
    statuses = ", ".join(f"'{s}'" for s in OPEN_STATUSES)
    parts = [f"{alias}.status::text IN ({statuses})", site_issue_sql(alias)]
    if counted:
        parts.append(counted_issue_sql(alias))
    return "(" + " AND ".join(parts) + ")"
