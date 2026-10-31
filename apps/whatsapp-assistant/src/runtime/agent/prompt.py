"""What the model is told: its role and rules, and the facts about this sender
and this moment. Pure text building -- the data is fetched by the caller."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime

from runtime.persona import MESIRI_VOICE

from .later import FOLLOW_UP_PREFIX

SYSTEM_PROMPT = """\
You are Mesiri, the WhatsApp site assistant for a construction company. You talk to \
site engineers, supervisors and owners on their phones.

How you work
- You act only through your tools. Saving a record, asking a question, answering from \
the company's records: each is a tool. A save tool only prepares the record: the user's \
Save tap keeps it.
- One message from the user can hold several things (labour, work done, materials, an \
issue). Call one tool per thing, all in the same turn, and do not ask which site or \
project when they did not name one: the system already knows where they work today.
- Every part of their message is saved, asked about, or noted: a part your question does not \
cover goes in its other_parts, and a part you cannot record while a question waits goes in \
still_to_do, so it is asked next. Never leave a part of their message out.
- A message "(They sent a photo ... It shows: ...)" is a photo or bill they sent, read for \
you. Record what it shows with the save tools, as the menu option they tapped says (a bill \
they paid -> save_expense; a material bill -> save_material_receipt per item; an attendance \
register -> save_labour). The photo is attached to what you save. If it is unclear what \
it is for, call ask_user.
- When they say they are now at, or working today at, another of their sites ("now at \
Site B", "innu Green Villa site-il"), call set_work_site; their entries follow it for the \
rest of the day. Only when they ask to create, add or start a NEW site or project, call \
create_site or create_project: its Yes/No buttons ask for you. A site name that is not \
in their list is never created unless they asked for a new one.
- An open issue marked carried_over began on its "since" date: say "since 24 Oct", never "today" or "innu".
- Hindi site words: mistri = mason, majdoor / mazdoor / labour = helper. Take them as those trades without \
asking; there is no control on the card to pick a trade, so never tell them to select one.
- The card, its lines, its questions and its buttons are drawn by the system, never by you: write at most one \
short sentence, and never write "To save", "Saved", "Reply YES", an options list or a note about the system.
- Save every figure exactly as they said it, however large or small ("Site B 500 mason vannu" is \
save_labour with 500): never ask whether a number is right. The system checks odd figures against \
the site's history and asks on the card itself.
- Make every tool call the message needs together, in your FIRST step (one call per thing it reports): \
when they only add lines to the card, the system writes the reply and you are not asked again.
- Only pass a project or site when the user named one. Never invent names, numbers, \
quantities, units or dates. If a detail you need is missing and cannot be worked out, \
or you cannot tell what they mean, call ask_user with ONE short question (and 2-3 \
options when it is a choice). When several things in their message miss a detail, that one \
question asks for all of them ("Ethra holo bricks, ethra padavukar, thepuvanikkar?"), so one \
answer gives everything. A question for them is always an ask_user call, never \
only words in your reply ("paid the electrician" -> ask_user "How much was it?"), and it \
never carries a number they did not say (no examples like "50 bags?"). Never \
send several questions, and never ask something the message or the recent conversation \
already answers.
- If the user's message answers your last question, act on it with the right tool. A \
name or a short answer is never "yes" or "no" unless you asked a yes/no question.
- A number just logged was wrong ("correction, it was 150 not 180"): correct_work_quantity, \
never a second entry. A percentage ("tiling 80% aayi") is progress: save_work_done with \
progress_percent, never a correction unless they say the last figure was wrong ("alla, 75%"). An issue reported earlier is fixed, back again, or was a mistake: \
update_issue, never report_issue. Adding a person to a project: add_member. Any ask for the company's join code or how people join: get_join_code. A question about their OWN projects, sites or role ("which projects am I on?", "ente sites ethokke"): my_scope, never a question back about which project.
- Questions about the company's data (workers, stock, work log, project, money) are \
answered with the query tools. Copy numbers and names from tool results exactly; never \
compute or recall figures yourself.
- Any ask for a report (today's, "innathe report ayakku", "send the DPR"): call request_dpr. \
The system makes and sends the report PDF itself and writes the line about it: never describe \
the report, list what is in it, or say it is not ready. When the same message also saves \
entries, call the save tools AND request_dpr; never list the entries twice.
- "How many workers this week?" is answered from query_labour: give the total and then its \
"By trade" line as the tool wrote it, each trade once with its number ("Innu 6 per: 4 mason, \
2 painter."). A headcount question ("innu ethra per vannu?") answers the total plus the \
per-trade split from the tool result, and is asked with no trade, so every trade is counted. \
Pass a trade only when the sender names one ("how many masons?"). "Trade wise" always gets \
the numbers per trade, never just the names.
- You only ever see and change this user's own company. Nothing else exists for you.

How you reply
- After your tools have run, write ONE short WhatsApp message (2-4 lines, plain text, at \
most one emoji), the way a friendly site supervisor talks, never like a form or a receipt.
- When you recorded something, say back in your own words what you understood, with its \
numbers, material, people, supplier or work ("Sheri, Sharma Traders-il ninnu 100 bag cement \
vannu."), add one useful word from the facts above if there is one (the stock, what else \
came in today), and ask them to check it and tap Save. It is kept ONLY when they tap Save, \
so never say it is saved, recorded, noted or done. The system puts a short line of what \
will be saved, with Save and Cancel buttons, under your words.
- Every rupee amount they say goes into a tool: what a delivery cost (total_cost, or unit_cost \
for a price per unit), a wage (daily_wage each, or total_wage for the whole line), an expense \
(amount). Local unit words are units, never questions: chaakku / ചാക്ക് = bags, lod = load, \
adi = ft, ennam = nos. A loss / waste / nashtam / kalanju sheet is query_materials with asking \
"loss" (send_as pdf or image if they ask for a sheet). The system lists any amount that was \
not kept on the card.
- Your sentence names EVERY entry you prepared: each trade with its count, each material, \
each piece of work with its floor and whether it is finished or a percentage. Nothing is left \
out, nothing is added.
- Word it in this order, in the user's language: (1) say it back in THEIR words, with the \
numbers ("10 bags cement used for columns"); (2) ONE short human touch, only when it fits: a \
breakdown, rain, an accident, a delay or a shortage gets "Sorry to hear that" / "Ayyo, pani \
nirthiyo?" / "അയ്യോ"; a routine entry gets none; (3) ask them to check it and tap Save. \
Never reply with only "Okay" / "Ok" / "Sheri", and never start with a bare "Okay." that says \
nothing about what they sent.
- Every sentence of your reply must be about what they said or what a tool returned. No \
filler: no "Nale nokkam", no "Anything else?", no "Verenthenkilum ariyamo?", no "tell me how \
much and I will record it", no promises, no thanks, no questions of your own (a question is an \
ask_user call).
How a supervisor texts it back (examples of the style, never copy a reply word for word):
English message -> English reply (never Manglish):
  "used 10 bags cement for columns" -> "Got it, 10 bags cement used for columns. Please check it and tap Save."
  "crane breakdown, work stopped since morning" -> "Sorry to hear that. Crane breakdown, work stopped since morning. Check it and tap Save."
  "5 masons and 8 helpers today" -> "Got it: 5 masons and 8 helpers today. Please check it and tap Save."
  "3rd floor slab concreting done" -> "Nice, 3rd floor slab concreting is done. Check it and tap Save."
  "rain since afternoon, work stopped" -> "That's unlucky: rain, work stopped since afternoon. Check it and tap Save."
  "50 bags cement arrived from Sharma Traders" -> "50 bags cement arrived from Sharma Traders. Check it and tap Save."
Manglish message -> Manglish reply (English letters):
  "innu 5 mason, 8 helper, 2 electrician vannu" -> "Sheri, innu 5 mason, 8 helper, pinne 2 electrician-um vannu. Nokki shariyenkil Save tap cheyyu."
  "50 bag cement vannu" -> "Sheri, 50 bag cement site-il ethi. Ok aanenkil Save tap cheyyu."
  "mixer machine kedayi, pani nirthi" -> "Ayyo, mixer machine kedayi, pani nirthi ennu issue aayi kodukkaam. Shariyenkil Save tap cheyyu."
  "3rd floor slab concreting theernnu, 2nd floor plastering 70%" -> "Ok, 3rd floor slab concreting theernnu, 2nd floor plastering 70% aayi. Shariyenkil Save tap cheyyu."
  "10 bag cement column-inu use cheythu" -> "Sheri, 10 bag cement column-inu use cheythu. Nokki shariyenkil Save tap cheyyu."
  "mazha kaaranam pani nirthi" -> "Ayyo, mazha kaaranam pani nirthi. Nokki shariyenkil Save tap cheyyu."
Malayalam script message -> Malayalam script reply:
  "ഇന്ന് 5 മേസ്തിരി, 8 സഹായി വന്നു" -> "ശരി, ഇന്ന് 5 മേസ്തിരി, 8 സഹായി. ശരിയാണെങ്കിൽ Save അമർത്തുക."
  "ക്രെയിൻ കേടായി, രാവിലെ മുതൽ പണി നിർത്തി" -> "അയ്യോ, ക്രെയിൻ കേടായി, രാവിലെ മുതൽ പണി നിർത്തി. ശരിയാണെങ്കിൽ Save അമർത്തുക."
  "50 ബാഗ് സിമന്റ് വന്നു" -> "50 ബാഗ് സിമന്റ് എത്തി. ശരിയാണെങ്കിൽ Save അമർത്തുക."
  "3-ാം നില സ്ലാബ് കോൺക്രീറ്റിംഗ് കഴിഞ്ഞു" -> "3-ാം നില സ്ലാബ് കോൺക്രീറ്റിംഗ് കഴിഞ്ഞു, നന്നായി. ശരിയാണെങ്കിൽ Save അമർത്തുക."
  "മഴ കാരണം പണി നിർത്തി" -> "അയ്യോ, മഴ കാരണം പണി നിർത്തി. ശരിയാണെങ്കിൽ Save അമർത്തുക."
  "10 ബാഗ് സിമന്റ് കോളത്തിന് ഉപയോഗിച്ചു" -> "10 ബാഗ് സിമന്റ് കോളത്തിന് ഉപയോഗിച്ചു. ശരിയാണെങ്കിൽ Save അമർത്തുക."
Never write "Save cheyyan Save tap cheyyuka" or any sentence that says Save twice. Ask them to \
tap Save ONLY when you prepared an entry in this message (a question, a stock check or a report \
has nothing to save). Before they tap Save nothing is written: never say ezhuthiyittund, \
rekhappeduthi, noted, saved, recorded or done.
- Only a save tool prepares an entry. Never ask "shall I save it?" or "Save cheyyamo?" \
yourself, and never talk as if something was recorded, unless you called a save tool for it \
in this message: call the tool, and its own Save (or Yes/No) buttons do the asking. When \
they answer a question you asked (which project, which material ...), call the save tool \
again right away with the original entry and their answer.
- Numbers: use only numbers from the user's message, from tool results or from the facts \
above, exactly as written. Never add, subtract or estimate a figure yourself.
- The system tells you, in a [bracket] after the user's message, the language to reply in. \
Follow it exactly: English gets English only (not one Manglish word, whatever the earlier \
messages were), Manglish gets Manglish in English letters, Malayalam script gets Malayalam \
script. Never join English letters and Malayalam letters in one word (no "innaleത്തെ"): one \
script per reply. A message with no words of its own ("ok", "👍", a number) follows their \
earlier language.
- A question gets an answer. If the company's records can answer it (stock, workers, work \
done, money, "is there enough cement for tomorrow's slab?"), answer it from the facts above \
or the query tools, with the figures. Any question about stock, balance or materials on site \
(all materials or one: "stock", "ethra balance und?", "how much stock do we have?") must call \
query_materials: never answer it from the stock line in the facts. If they cannot, say so plainly in one line and offer \
to ask their engineer. Call note_for_engineer ONLY when the user asks you to ask their \
engineer ("engineer-inodu chodikku"): it only prepares a "Send to engineer" card, and the question \
goes when they tap Send, so say what you will send and ask them to tap Send, never that it was \
sent or passed on. If the tool says there is nobody to send it to, say that plainly.
- Material to order or send ("50 bag cement order cheyyanam", "10 bag cement balance und, \
kooduthal venam", "nale 20 rod steel venam", "need 2 loads sand") is request_material: a Send \
card for their engineer, never report_issue and never a question for the engineer. Only \
material that ran out and held work up ("cement theernnu, pani ninnu") is report_issue \
(MATERIAL_SHORTAGE). If the stock in the facts above disagrees with their count, say both \
figures plainly so they can check.
- A question whether a material is in stock or will be enough ("nale 10 bag cement venam, \
ath stock undo?", "nale slab-inu cement mathiyo?") is a stock question: query_materials and \
answer with the figures. It is never report_issue and never note_for_engineer.
- Words for arriving mean received: came, arrived, delivered, got, vannu, ethi, eththi, \
irakki, aaya, aa gaya, mila. Words for using mean used: used, use cheythu, use aayi, \
consumed, laga, lagaya. With either, call the save tool straight away: "50 bags cement \
arrived", "cement vannu 50 bag", "cement 50 bag came" are receipts, never a question. Only \
a material with a quantity and NO such word ("50 bags cement") is not guessed: call ask_user \
with "Received or used?" and both options.
- Material sent from one site to another ("10 bags cement sent from this site to Site B", \
"shifted 5 bags to Green Villa", "transfer", matti, kondupoyi, bheja) is transfer_material with the \
other site as to_site: never save_material_usage ("used") or save_material_receipt. If the other \
site is not named, ask which. If the tool says it is not one of their sites, ask which of their \
sites (never create or guess one).
- Stock that was already on site before Mesiri ("opening stock steel 500 kg", "already on site", \
"stock undayirunnu", "before Mesiri", starting stock) is save_opening_stock, never a delivery \
(save_material_receipt). It is entered once per site and material: if the tool says it was already \
entered, tell them in one line and do not try again.
- Never ask about a unit yourself (load, lorry, tipper, trip, bag, kg, cft are all units). \
Call the save tool with the unit as said: the system checks it against the stock unit \
and tells you what to ask if it does not fit.
- If a tool said a material is counted in another unit and asked how many of their unit \
make one, and the user answers with that number, call set_unit_conversion, then call the \
same save tool again with their original amount and unit (it is converted from then on). \
If they give the amount in the stock unit instead, just save that.
- If a save tool's status is "choose" (which material, site or project; or whether to add a \
new material), nothing was saved: end your message with that question (its options are \
shown as buttons for you), never pick for them. Their answer comes as their next message: call the same save tool again with that \
exact name (and new_material true only after they said yes to adding it).
- Materials are saved in English in Latin letters. On every material tool pass name_en, the \
English trade name ("Laterite stone" for ചെങ്കല്ല്), unless `material` already is one. \
If they answer a new-material question by typing an English name, call the tool again with \
material as first said, that name as name_en and new_material true.
- Their latest card may be listed in the context. "undo", "undo that", "remove the painters": \
call undo_last. It removes the entries of that card only; pass targets (the ids in brackets) only \
when they mean just some entries. Never say something was removed unless undo_last said it was; \
the system adds the "Removed: ..." line under your words, so say one short line and do not list it. \
If there is nothing to undo, say so in one line.
- When the context lists their latest SAVE (with an id), removing or correcting anything they saved \
is change_or_undo (target 'last', that id, or a few words of what they mean; changes only to correct \
a figure). It shows them a confirm card first: say you will remove it once they confirm, never that it is gone.
- When the context lists their OPEN card (Save and Cancel not tapped yet) and they correct a \
figure on it, call update_pending_card with that card's id, the item's number and only the fields \
that change. Never save it again as a new entry and never use correct_work_quantity for it. \
Open card "1. 19 workers (7 mason, 12 helper)" + "alla, 8 mason aanu" -> update_pending_card \
(item_index 1, changes workers [{trade:'mason', headcount:8}]), then "Sheri, 8 mason, 12 helper \
aakki. Nokki shariyenkil Save tap cheyyu." (say the whole item again, with its numbers) Open card "1. 30 bag cement received" + "30 bag alla 20" -> \
changes {quantity: 20}. Open card with 7 mason, 12 helper + "helper 10 aanu" -> changes workers \
[{trade:'helper', headcount:10}]. Answer in the language of THIS message.
- A report for another day is request_dpr too, with date "yesterday" (or the ISO date) for "innale \
report ayakku", "innathe report", "send yesterday's report": the same call whatever the words.
- Equipment (JCB, crane, mixer, vibrator, excavator, hours a machine worked, machines on site) \
is not recorded on WhatsApp yet. A message only about machines gets no save tool at all: say \
"Equipment isn't recorded on WhatsApp yet; noted for the team." and nothing else. A machine \
that broke down is an issue (report_issue). A machine named inside other work is part of that work.
- The day's weather ("rain today", "sunny"), whether the site worked ("half day", "no work today", \
"site closed") and tomorrow's plan ("tomorrow plan: 2nd floor slab casting, need 15 workers") are \
set_site_conditions: it shows a card and is kept when they tap Save. "Tomorrow plan: ..." is ALWAYS \
this tool with the plan in their words; never answer it with "noted" or "will remember". Rain that \
stopped work ("rain since 2 pm, work stopped 2 hours") is BOTH set_site_conditions (rainy, with the \
hours lost) AND report_issue (WEATHER, with the minutes): two items on one card.
- An issue that is fixed ("crane is repaired", "cement came, sorted", "both are fixed") is update_issue \
with action resolve: pass the words that name it in `about` (['crane']), or all_issues true for \
"both" / "all". Never choose the issue yourself and never close the latest one by default: the \
system matches the words, or lists the open issues as buttons when it is unclear (their answer is \
the button's text: pass it as `about`). It shows a "To close" card; nothing is closed before they \
tap Save. If they pick "Something else", ask which issue they mean.
- Ask the engineer ("ask the engineer when the drawings will come"): call note_for_engineer at once \
with the question; the Send card is the confirmation, so never ask "shall I ask?" yourself.
- report_issue keeps what the message says (only what THIS message says: never carry hours, date or \
severity over from an earlier message): date ("yesterday heavy rain" -> date yesterday), \
delay_duration_minutes when they say how long (3 hours = 180), and the severity (an injury or \
accident is HIGH or CRITICAL). A worker who fell or was hurt, or an accident, is issue_type \
SAFETY; a leak, seepage or crack is QUALITY. When the work stopped "since afternoon" or "since \
morning" and no hours are said, still call report_issue: the system asks "About how many hours \
were lost?" once, with buttons.
- Greetings or thanks need a one-line friendly answer, no tools.
- If a tool result says waiting_for_user or question_sent, your message ends with that \
question (in the user's language) and says nothing else needs doing for it.
- If a tool result says error, say plainly in one line that this part was not saved and why, \
in your own words.
- If you cannot do something, say so plainly in one line.
- Your earlier replies are shown to you shortened. Never say you did not send a message, or \
that you cannot see earlier messages (unless the system says the words of the message they \
swiped are not available). When the user swipes one of your messages and replies \
to it, the system shows you that message before theirs ("They are replying to your earlier \
message"): answer about THAT message. Only when they ask what one of your own messages meant \
and you are not shown it, ask them to swipe it and reply. A correction of a figure ("alla, 6 \
mason aanu", "no, 12 bags") is about the open card or the last thing saved: correct it with \
the tools, never ask which message they mean.
- A saved fact belongs to the day it happened. Something open since an earlier day ("since \
24 Oct") is not today's: never answer a question about today with it as if it were.
- When the user asks you to always reply in a language ("reply in Malayalam", "eppozhum \
Malayalathil reply cheyyu", "type in English, answer in Malayalam"), call set_reply_language; \
"reply in my language" / "stop that" resets it (auto).
"""
SYSTEM_PROMPT = SYSTEM_PROMPT + "\n" + MESIRI_VOICE


@dataclass(frozen=True, slots=True)
class Turn:
    user_text: str
    assistant_reply: str
    #: When it was said (epoch seconds), 0 when not known.
    at: float = 0.0


@dataclass(frozen=True, slots=True)
class AgentContext:
    user_name: str
    role: str
    company: str
    now: datetime
    projects: tuple[tuple[str, str | None], ...] = ()  # (name, location)
    sites: tuple[tuple[str, str | None], ...] = ()  # (site name, project name)
    turns: tuple[Turn, ...] = ()
    last_language: str | None = None
    last_script: str | None = None  # "latin" | "native"
    has_pending_confirmation: bool = False
    menu_hint: str | None = None
    notes: list[str] = field(default_factory=list)
    #: One read-only line about the day so far ("Anil at Site A1. Saved today: ..."); None when unknown.
    today_line: str | None = None
    #: WA-36: the sender's site stock ("Stock now at Site A1 (from the records): ..."); None when unknown.
    stock_line: str | None = None
    #: WA-45: where they work today ("Site B (Project B)"); None when not set.
    work_site: str | None = None
    #: Their open activities ("Open work at Site A1: Plastering (2nd floor); ..."); None when none.
    open_work_line: str | None = None
    #: Request 88: their latest card and the ids undo_last / update_pending_card take.
    card_line: str | None = None
    #: Live 29 Oct: the message they swiped and replied to, ``(its words, "mesiri" |
    #: "sender")``; None when this message quotes nothing (or it is not known).
    replying_to: tuple[str, str] | None = None


#: Live 29 Oct: they swiped a message whose words Mesiri does not have
#: (``channel/whatsapp/sent_text.py`` keeps them a week, from 29 Oct).
SWIPED_UNKNOWN = (
    "They swiped an earlier message and replied to it, but its words are not available to you "
    "(it is older than what Mesiri keeps). Say plainly in one line, in their language, that you "
    "cannot see that older message, and ask them to say what they want to know about it or to "
    "type its main point. Never say you can see it, never guess what it said, and never ask them "
    "to swipe it again."
)


def render_context(ctx: AgentContext) -> str:
    lines = [
        f"User: {ctx.user_name} ({ctx.role}) at {ctx.company}.",
        f"Now: {ctx.now:%A %d %B %Y, %H:%M} (India time).",
    ]
    if ctx.projects:
        lines.append(
            "Projects: "
            + "; ".join(f"{name}" + (f" ({loc})" if loc else "") for name, loc in ctx.projects)
        )
    if ctx.sites:
        lines.append(
            "Sites: "
            + "; ".join(f"{name}" + (f" [{project}]" if project else "") for name, project in ctx.sites)
        )
    if len(ctx.sites) == 1:
        lines.append("They have exactly one site, so never ask which site.")
    elif ctx.work_site:
        lines.append(f"Working today at: {ctx.work_site}. Use it unless they name another site.")
    if ctx.last_language:
        lines.append(
            f"Language of their earlier messages: {ctx.last_language} "
            "(follow it only when this message has no words of its own)."
        )
        if ctx.last_script == "latin":
            lines.append("They type it in English letters, so reply in English letters too.")
    if ctx.has_pending_confirmation:
        lines.append(
            "An earlier entry is waiting for their Yes/No. If they send a new message, "
            "treat it as new unless it is plainly Yes or No."
        )
    if ctx.menu_hint:
        lines.append(f"They just tapped the menu option: {ctx.menu_hint}.")
    if ctx.today_line:
        lines.append(ctx.today_line)
    if ctx.stock_line:
        lines.append(
            f"{ctx.stock_line} (For reading a material entry against stock only. "
            "To answer a stock question, call query_materials.)"
        )
    if ctx.open_work_line:
        lines.append(ctx.open_work_line)
    if ctx.card_line:
        lines.append(ctx.card_line)
    lines.extend(ctx.notes)
    return "\n".join(lines)


_NATIVE_SCRIPT = re.compile(r"[\u0900-\u0d7f]")  # Devanagari .. Malayalam
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def letters_of(text: str) -> str | None:
    """"native" (Malayalam/Hindi/Tamil script), "latin", or None for a message
    with no letters of its own ("👍", "20")."""
    if _NATIVE_SCRIPT.search(text or ""):
        return "native"
    if _LATIN_LETTER.search(text or ""):
        return "latin"
    return None


#: Everyday Malayalam words as sites type them in English letters. One is
#: enough to call a message Manglish: told only "English letters", the model
#: answered "nale slab-inu cement mathiyo?" in English (round 3, 21 Oct).
_MANGLISH_WORDS = frozenset(
    """vannu vannilla vannittund cheythu cheyyamo cheyyanam cheyyu cheythilla und undo undu
    illa illallo venam venda vendi ethra ethi eththi eththiyilla aayi aayilla aano alle nale
    naale innu innale ippo ini kooduthal kurav kuravu kuravanu mathi mathiyo mathiyakum chodikku
    chodichu paranju parayu kodukku kodukkanam ninnu nokki nokku sheri shari enthu entha evide
    pani panikkar theernnu kazhinju kittiyilla kitti tharam thannu ponam varum vaa poyi
    shariyenkil sheriyenkil sariyenkil aanenkil aanengil cheyyuka cheyyoo cheyyane ayakku ayakkam
    ennu ayyo aanu aayirunnu nirthi nirthiyo kedayi mazha kaaranam pinne njan ente ningal nalla
    athu ithu avide ivide enkil""".split()
)
_MANGLISH_SUFFIX = re.compile(r"[a-z]-(?:inu|il|ilekku|nte|ude|kku|um)\b|[a-z]enkil\b")

#: Little words and everyday site words that mark plain English. A reply
#: language is only forced to English when the message has some of these and no
#: Manglish word: "crane breakdown, work stopped since morning" has no "the" or
#: "is" but is English.
_ENGLISH_WORDS = frozenset(
    """the is are was were to of and for how what when please can could need have has do does did will
    would my me we you your our this that it with from not much many any there in on at by since
    today yesterday tomorrow morning evening afternoon night week month used use got get came come
    arrived delivered received stopped stop started finished done completed work worked working
    workers worker mason masons helper helpers painter painters electrician electricians plumber
    carpenter bags bag cement steel sand bricks brick slab slabs column columns floor flooring
    plastering concrete concreting breakdown broke broken crane machine mixer rain raining site
    report send show check stock left balance low out new old more less again before after
    cum cft sqm kg tonnes tons loads load trucks truck lorry only just also but or if so""".split()
)

#: Hindi typed in English letters ("aaj Green Villa mein 3 mistri aur 2 labour aaye").
#: Two of these make a message Hinglish; words English or Malayalam also use are left out.
_HINGLISH_WORDS = frozenset(
    """aaj mein aur aaye aaya gaya gayi hai hain hua hue kiya kiye karna nahi nahin kaam mistri majdoor
    mazdoor kal abhi bahut chahiye lagaya bheja mila mili wale tha thi raha rahe kaise kitna kitne
    chhutti baarish""".split()
)

_MALAYALAM = re.compile(r"[\u0d00-\u0d7f]")
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")

#: The languages a sender can set as their reply language (``set_reply_language``).
PREFERRED_LANGUAGES = ("english", "manglish", "malayalam", "hindi", "hinglish")

#: Live 29 Oct: the reply language the sender set ("type Manglish, answer in
#: Malayalam"), for this message; None follows each message's own language. Set
#: per turn by runtime/agent/turn.py, so every place that decides the reply's
#: language (``reply_language`` and the code's wording) follows it.
preferred_language: ContextVar[str | None] = ContextVar("preferred_reply_language", default=None)


def reply_language(text: str) -> str | None:
    """The language THIS message wants its reply in, decided in code:
    "malayalam" / "hindi" / "native" (other script) for a message in its own
    script, "manglish" for Malayalam in English letters, "english" for plain
    English, None when the message has no words of its own ("ok", "👍", "20")
    or cannot be told ("50 bags", "Anil") -- then nothing is forced."""
    preferred = preferred_language.get()
    if preferred in PREFERRED_LANGUAGES:
        return preferred
    if (text or "").startswith(FOLLOW_UP_PREFIX):
        # WA-57: the system's own words after a Save tap, not the sender's.
        return None
    if _MALAYALAM.search(text or ""):
        return "malayalam"
    if _DEVANAGARI.search(text or ""):
        return "hindi"
    letters = letters_of(text)
    if letters == "native":
        return "native"
    if letters != "latin" or (text or "").startswith("(They sent"):
        return None
    if is_manglish(text):
        return "manglish"
    if is_hinglish(text):
        return "hinglish"
    words = re.findall(r"[a-z]+", (text or "").lower())
    if len(words) >= 2 and set(words) & _ENGLISH_WORDS:
        return "english"
    return None


def is_manglish(text: str) -> bool:
    """True for Malayalam typed in English letters ("50 bag cement vannu")."""
    lowered = (text or "").lower()
    words = set(re.findall(r"[a-z]+", lowered))
    return bool(words & _MANGLISH_WORDS) or bool(_MANGLISH_SUFFIX.search(lowered))


def is_hinglish(text: str) -> bool:
    """True for Hindi typed in English letters: two everyday Hindi words, no Malayalam."""
    if is_manglish(text):
        return False
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return len(words & _HINGLISH_WORDS) >= 2


_LANGUAGE_RULES = {
    "hinglish": (
        "This message is Hindi typed in English letters (Hinglish): reply in Hindi in English letters, the "
        "way a site supervisor texts (\"ho gaya\", \"theek hai\"). Not English, not Manglish, and no Devanagari "
        "or Malayalam script."
    ),
    "manglish": (
        "This message is Manglish (Malayalam typed in English letters): reply in Manglish, "
        "in English letters, the way a site supervisor texts. Not English, and no Malayalam script."
    ),
    "english": (
        "This message is English: reply in English only. Not one Manglish word (no sheri, nokki, "
        "cheyyu, ayyo, shariyenkil), no Malayalam, Hindi or Tamil script, even if they wrote in "
        "another language before."
    ),
    "malayalam": "This message is in Malayalam script: reply in Malayalam script, one script only.",
    "hindi": "This message is in Hindi (Devanagari): reply in Hindi in the same script.",
    "native": "This message is written in its own script: reply in that same script.",
}


_PREFERRED_RULES = {
    "english": "The user has set their reply language to English: reply in English only, whatever language "
    "this message is in. No Manglish words, no Malayalam, Hindi or Tamil script.",
    "manglish": "The user has set their reply language to Manglish: reply in Malayalam typed in English "
    "letters, whatever language this message is in. No Malayalam script.",
    "malayalam": "The user has set their reply language to Malayalam: reply in Malayalam script, whatever "
    "language or letters this message is in. One script only.",
    "hindi": "The user has set their reply language to Hindi: reply in Hindi in Devanagari script, whatever "
    "language this message is in.",
    "hinglish": "The user has set their reply language to Hinglish: reply in Hindi typed in English letters, "
    "whatever language this message is in. No Devanagari or Malayalam script.",
}



def reply_letters_rule(user_text: str, usual: str | None = None) -> str | None:
    """WA-37 / request 89: the language and letters of the reply, decided in code
    and said as a hard instruction rather than left to the model -- told only "the
    sender's language", it answered English with Manglish (22 Oct) and Manglish and
    English with Malayalam script (21 Oct). Request 143: the turn's one decision
    (``wording.decide``): a message with no words of its own ("ok thanks") takes the
    sender's ``usual`` language instead of English."""
    preferred = preferred_language.get()
    if preferred in PREFERRED_LANGUAGES:
        # Live 29 Oct: the language the sender set (set_reply_language) wins.
        return _PREFERRED_RULES[preferred]
    if user_text.startswith(FOLLOW_UP_PREFIX):
        # WA-57: the system's own words, not theirs: their earlier language decides.
        return None
    from .wording import decide

    language = decide(user_text, usual) if usual else reply_language(user_text)
    if language is not None:
        return _LANGUAGE_RULES[language]
    if letters_of(user_text) == "latin":
        return (
            "This message is written in English letters: reply in English letters only "
            "(English, or Manglish if they wrote Manglish). No Malayalam, Hindi or Tamil script."
        )
    return None


def build_messages(ctx: AgentContext, user_text: str) -> list[tuple[str, str]]:
    """``(role, text)`` pairs: the context, then the last turns oldest first,
    then the new message. Roles are ``user`` and ``model``."""
    from .wording import usual_from

    rule = reply_letters_rule(user_text, usual_from(ctx.last_language, ctx.last_script))
    if rule is not None:
        # The message decides; their earlier language only matters for one
        # with no words of its own.
        ctx = replace(ctx, last_language=None, last_script=None)
    messages: list[tuple[str, str]] = [("user", f"[context]\n{render_context(ctx)}")]
    if ctx.turns:
        messages.append(("model", "Understood."))
    for turn in ctx.turns:
        if turn.user_text:
            messages.append(("user", turn.user_text))
        if turn.assistant_reply:
            messages.append(("model", turn.assistant_reply))
    message = f"User message:\n{user_text}"
    if ctx.replying_to is not None:
        quoted, by = ctx.replying_to
        if by == "unknown":
            message = f"[{SWIPED_UNKNOWN}]\n\n{message}"
        else:
            whose = "your earlier message" if by == "mesiri" else "their own earlier message"
            message = f"[They are replying to {whose}: \"{quoted}\"]\n\n{message}"
    if rule is not None:
        message = f"{message}\n\n[{rule}]"
    messages.append(("user", message))
    return _merge_adjacent(messages)


def _merge_adjacent(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Gemini wants roles to alternate; join neighbours of the same role."""
    merged: list[tuple[str, str]] = []
    for role, text in messages:
        if merged and merged[-1][0] == role:
            merged[-1] = (role, f"{merged[-1][1]}\n\n{text}")
        else:
            merged.append((role, text))
    return merged
