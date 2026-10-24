"""Equipment is not recorded on WhatsApp yet (request 104, A1).

"JCB worked 6 hours today" and "2 mixers and 1 vibrator on site today" were
answered "✅ Saved" with nothing behind them. Until the equipment section
exists (part 2), a message that is only about equipment gets one plain line:
no save tool runs, no Save card is offered, and the message itself stays in the
conversation log the team reads. A message that mentions a machine as part of
other work ("concreted 20 cum slab with the mixer") is not equipment-only and
is saved as before; so is a breakdown (that is an issue).
"""

from __future__ import annotations

import re

EQUIPMENT_LINE = "Equipment isn't recorded on WhatsApp yet; noted for the team."

_EQUIPMENT = re.compile(
    r"\b(?:jcb|jcbs|poclain|excavators?|crane|cranes|hydra|mixers?|vibrators?|rollers?|"
    r"dumpers?|tippers?|bobcat|loaders?|compressors?|breakers?|pumps?|graders?|"
    r"concrete pump|batching plant|transit mixers?|tractors?|trucks?|lorry|lorries|"
    r"machines?|machinery|equipments?)\b",
    re.IGNORECASE,
)
#: Words that make a message a problem, not an equipment log: that is an issue.
_PROBLEM = re.compile(
    r"break\s?down|broke|broken|repair|fault|not working|stopped|stuck|accident|"
    r"kedayi|kedaayi|kedu|nirthi|theernnu|problem|leak",
    re.IGNORECASE,
)
_FILLER = frozenset(
    "worked work working today on site and the a an in at for was were is are came come arrived "
    "available used running ran hrs hours hour hr nos no units unit machine machines from since "
    "morning afternoon evening innu vannu und undu undayirunnu aayi cheythu pani yesterday with "
    "of to by total full half day all one two three four five six seven eight nine ten".split()
)


def is_equipment_only(text: str) -> bool:
    """Whether the whole message is about machines on site or their hours."""
    text = text or ""
    if not _EQUIPMENT.search(text) or _PROBLEM.search(text):
        return False
    rest = _EQUIPMENT.sub(" ", text.casefold())
    words = re.findall(r"[^\W\d_]{2,}", rest)
    return not [w for w in words if w not in _FILLER]
