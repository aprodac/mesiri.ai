"""Which tools a turn shows the model (request 143, phase 4: speed).

Every tool spec went with every model call: 31 tools, ~30K characters, two or three
times a message. A message about labour needs the labour tools, not the money or team
ones. ``tools_for`` picks the families a message's words name, plus the core every
turn may need (a question, the card, undo and change, the work site).

Safe by construction: a message that names no family ("50", "ok sheri", a voice note
about something new) gets every tool, as before; families are wide (a material word
brings every material tool), and a turn that already has an answer or a question
waiting keeps every tool. A missed family costs only that the model cannot call it
this turn; the prompt is unchanged.
"""

from __future__ import annotations

import re

from . import tools as t

#: Every turn: one question, the still-to-do note, the card, undo / change, the site.
CORE = frozenset(
    {t.ASK_USER, t.STILL_TO_DO, t.UPDATE_PENDING_CARD, t.CHANGE_OR_UNDO, t.UNDO_LAST, t.SET_WORK_SITE, t.MY_SCOPE}
)

_W = r"(?<![\w]){}(?![\w])"


def _words(pattern: str) -> re.Pattern[str]:
    return re.compile(_W.format(f"(?:{pattern})"), re.IGNORECASE)


#: family -> (the words that name it, its tools)
FAMILIES: dict[str, tuple[re.Pattern[str], frozenset[str]]] = {
    "labour": (
        _words(
            r"masons?|mestri|mistri|helpers?|workers?|labou?rs?|labourers?|majdoor|mazdoor|coolie|painters?|"
            r"electricians?|plumbers?|carpenters?|welders?|bar ?benders?|fitters?|per|aal|aalukal|attendance|"
            r"headcount|vannu|vannilla|came|absent|leave|ആൾ|പേർ|മേസൺ|ഹെൽപ്പർ|मिस्त्री|मजदूर"
        ),
        frozenset({t.SAVE_LABOUR, t.QUERY_LABOUR}),
    ),
    "work": (
        re.compile(
            _W.format(
                r"(?:work\w*|pani|done|finished|completed|theernnu|kazhinju|cheythu|tiling|tiles?|plaster\w*|"
                r"slab|concret\w*|casting|brick ?work|block ?work|masonry|painting|putty|shuttering|"
                r"excavation|footing|column|beam|flooring|waterproof\w*|wiring|plumbing|floor|sq ?ft|sqft|"
                r"sqm|rft|running ?ft|cum|progress|aayi|ആയി|പണി|काम)"
            )
            + r"|\d\s*%",
            re.IGNORECASE,
        ),
        frozenset({t.SAVE_WORK_DONE, t.CORRECT_WORK_QUANTITY, t.QUERY_WORK_LOG}),
    ),
    "material": (
        _words(
            r"cement|sand|m-?sand|p-?sand|steel|tmt|rods?|bricks?|blocks?|aggregate|jelly|metal|bags?|loads?|"
            r"kgs?|tons?|tonnes?|litres?|brass|cft|stock|materials?|tiles?|pipes?|wire|paint|received|arrived|"
            r"delivered|used|use|order\w*|venam|transfer\w*|shift\w*|opening|count\w*|pending|സിമന്റ്|മണൽ|കമ്പി|सीमेंट|रेत"
        ),
        frozenset(
            {
                t.SAVE_MATERIAL_RECEIPT,
                t.SAVE_MATERIAL_USAGE,
                t.TRANSFER_MATERIAL,
                t.SAVE_OPENING_STOCK,
                # "cement stock kazhinju": a material that ran out is a shortage report.
                t.REPORT_ISSUE,
                t.ADJUST_STOCK,
                t.QUERY_OPEN_NEEDS,
                t.QUERY_MATERIALS,
                t.SET_UNIT_CONVERSION,
                t.REQUEST_MATERIAL,
            }
        ),
    ),
    "money": (
        re.compile(
            _W.format(
                r"(?:paid|pay|payment|expense\w*|spent|cash|rupees?|rs|inr|amount|bill|petty|advance|wages?|"
                r"kooli|kodu\w*|kodutthu|nalki|account|balance|transfer\w*|fuel|diesel|rent|hire|diye|diya|"
                r"diyaa|dena|kharch\w*|chai|tea|food|bhojan|lunch|snacks?|purchase\w*|bought|vaangi\w*)"
            )
            + r"|₹",
            re.IGNORECASE,
        ),
        frozenset({t.SAVE_EXPENSE, t.TRANSFER_MONEY, t.QUERY_EXPENSES}),
    ),
    "site_problem": (
        _words(
            r"breakdown|broke\w*|kedayi|keday|problem|issues?|stopp?\w*|ninnu|nirthi|delay\w*|leak\w*|crack\w*|"
            r"accident|injur\w*|safety|shortage|short|less|kuravu|kuravaanu|not ?enough|only|theernnu|ran ?out|fixed|repaired|sorted|resolved|closed?|"
            r"engineer|drawing\w*|question|ask|chodikku|rain\w*|mazha|weather|sunny|holiday|half ?day|"
            r"tomorrow|nale|naale|plan|jcb|crane|mixer|vibrator|machine|pump|generator|മഴ|കേടായി"
        ),
        frozenset(
            {
                t.REPORT_ISSUE,
                t.UPDATE_ISSUE,
                t.NOTE_FOR_ENGINEER,
                t.SET_SITE_CONDITIONS,
                t.REQUEST_MATERIAL,
                t.ADJUST_STOCK,
                t.QUERY_OPEN_NEEDS,
            }
        ),
    ),
    "language": (
        _words(r"english|malayalam|manglish|hindi|hinglish|tamil|language|bhasha|bhaasha|reply|parayu|script"),
        frozenset({t.SET_REPLY_LANGUAGE}),
    ),
    "equipment": (
        _words(r"jcb|crane|mixers?|vibrators?|excavators?|machines?|pumps?|generators?|hitachi|tipper|roller"),
        frozenset({t.SAVE_WORK_DONE, t.SAVE_LABOUR, t.REPORT_ISSUE}),
    ),
    "report": (
        _words(
            r"reports?|dpr|summary|enthokke|enthu|what|ethra|how|today|innu|innale|yesterday|week|month|"
            r"details?|status|show|send|ayakku|list|total|റിപ്പോർട്ട്"
        ),
        frozenset(
            {t.REQUEST_DPR, t.QUERY_WORK_LOG, t.QUERY_PROJECT, t.QUERY_LABOUR, t.QUERY_MATERIALS, t.QUERY_OPEN_NEEDS}
        ),
    ),
    "team": (
        _words(
            r"add|member|members|team|join|code|invite|new ?site|new ?project|create|site ?create|project|"
            r"engineer|supervisor|manager|phone|number"
        ),
        frozenset({t.ADD_MEMBER, t.GET_JOIN_CODE, t.CREATE_SITE, t.CREATE_PROJECT, t.QUERY_PROJECT}),
    ),
}


def families_of(text: str) -> set[str]:
    return {name for name, (words, _tools) in FAMILIES.items() if words.search(text or "")}


#: Malayalam, Devanagari and other scripts join words with their endings ("മഴയാണ്"),
#: so word matching cannot tell their families: every tool.
_NATIVE = re.compile(r"[\u0900-\u0dff]")


def tools_for(text: str, *, keep_all: bool = False) -> list[t.ToolSpec]:
    """The tool specs for a turn, in the usual order. ``keep_all``: an answer to a
    question the turn is waiting on, a follow-up, or anything else whose needs the
    words cannot tell: every tool."""
    specs = t.tool_specs()
    found = families_of(text)
    if keep_all or not found or _NATIVE.search(text or ""):
        return specs
    names = set(CORE)
    for family in found:
        names |= FAMILIES[family][1]
    return [spec for spec in specs if spec.name in names]
