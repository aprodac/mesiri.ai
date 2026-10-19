"""A question nobody can answer from the records is noted for the engineer
(request 57, B2).

"Nale slab concrete cheyyan pattumo?" inside a site note used to be echoed
back and dropped. It is now saved as a low-severity open issue whose note
starts "Question for your engineer:", so it reaches the engineer through what
they already read (the site's open issues and the day's report) and the reply
can say so truthfully. Shared by the agent's ``note_for_engineer`` tool and the
classic note-with-a-question path.
"""

from __future__ import annotations

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType

QUESTION_PREFIX = "Question for your engineer: "
_MAX = 300


def question_note_candidate(question: str) -> Candidate:
    text = " ".join(str(question or "").split())[:_MAX]
    return Candidate(
        semantic_type=SemanticType.SITE_ISSUE,
        fields={
            "issue_type": "OTHER",
            "severity": "LOW",
            "narrative": f"{QUESTION_PREFIX}{text}",
        },
    )
