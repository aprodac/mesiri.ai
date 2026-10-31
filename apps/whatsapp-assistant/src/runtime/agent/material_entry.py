"""ARCH-01: a material receipt or usage from the agent, without the classic pipeline.

The agent's save_material_receipt / save_material_usage used to run through
``process_inbound_message`` (canonicalize -> gates -> planner -> graph) and
have its replies captured. Here the tool's arguments become the workflow's
event directly (ADR section 10b). What stays exactly as it was:

- who the sender is, their company, and which project/site they may use:
  ``ContextResolver.resolve``, unchanged (no new permission logic);
- the save: ``WorkflowRuntime.start`` + save-first, unchanged (idempotency,
  single-active guard, validation, posting).

What is plain code here instead of pipeline stages: the date, the material
(exact catalogue name only), the stock unit (``runtime/material_units``), the
module switch, and the stock figure (by material id, not by name).

When the sender must choose (which material, project or site, or whether to
add a new material), the model is told the options and asks with its own
``ask_user``; the answer comes back as a new call with the exact name
(ARCH-04: the old picker buttons resumed a held report and saved on the tap,
past the Save card). Only a failed context or catalogue lookup returns
``None``, and the caller runs the classic route for that call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from canonicalization.occurred_date import resolve_occurred_date
from channel.receipt.data import company_zone
from mesiri.domains.materials.names import alias_key
from mesiri.domains.materials.validation import OPENING_STOCK, role_can_adjust
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.entity_resolution.material_resolution import classify_material_matches
from runtime.material_units import (
    amount_question,
    ask_amount_text,
    conversion_question,
    fit_stock_unit,
    stock_unit_code,
)

from .entry_base import (
    SCOPE_KEYS,
    EntryScope,
    Ready,
    Say,
    choose,
    number,
)
from .material_names import EnglishName, english_name

__all__ = ["MaterialEntry", "Ready", "Say"]

_log = logging.getLogger("mesiri.agent")

_MODULE = "materials"
_BY_DIRECTION = {
    "received": (CanonicalEventType.MATERIAL_RECEIPT_REQUESTED, WorkflowKey.MATERIAL_RECEIPT),
    "used": (CanonicalEventType.MATERIAL_USAGE_REQUESTED, WorkflowKey.MATERIAL_USAGE),
    # [103]: stock that was on site before Mesiri is a receipt with its own reason.
    "opening_stock": (CanonicalEventType.MATERIAL_RECEIPT_REQUESTED, WorkflowKey.MATERIAL_RECEIPT),
    "transfer": (CanonicalEventType.MATERIAL_TRANSFER_REQUESTED, WorkflowKey.MATERIAL_TRANSFER),
}

#: [103]: the last choice of a long material list: they type the name instead.
SOMETHING_ELSE = "Something else"
#: What an answer fills in (``Say.awaiting``), so a card line waiting on the
#: question can take the answer from a tap (request 127): how many stock units
#: one reported unit is, and whether to add a new material.
AWAIT_UNIT = "unit"
AWAIT_NEW_MATERIAL = "new_material"
#: The amount in the stock unit, typed (no conversion to ask for): a card line
#: waits on it (request 129).
AWAIT_AMOUNT = "amount"
ADD_IT = "Yes, add it"
#: Request 159 (part D): the add choice shown after the closest listed materials.
ADD_NEW = "➕ Add "
#: A listed material this close to a new name is offered first ("Same as Steel rods?").
NEAR_DUPLICATE = 0.55
NEAR_LIMIT = 3
_ROW_TITLE = 24


_NAME_NOTE = (
    "Materials are saved in English: when you call this tool again, always pass name_en, the "
    "English trade name in Latin letters ('Laterite stone'). If they type an English name for it, "
    "call again with material as first said and name_en = what they typed, as a new material."
)


def _name_question(named: EnglishName, said: str) -> str:
    """What will be stored, and the way to change it (request 165 C)."""
    if named.sure:
        if named.name.casefold() == " ".join(said.casefold().split()):
            return ""
        return f' It will be saved as "{named.name}".'
    return f' Name it "{named.name}"? Or type the English name.'


def add_new_label(name: str, said: str = "") -> str:
    """"➕ Add Laterite stone (ചെങ്കല്ല്)": the English name that will be stored, with
    the word they said in brackets when it fits a WhatsApp row title (request 165)."""
    base = ADD_NEW + name.strip()
    word = " ".join(said.split())
    if word and word.casefold() != name.strip().casefold():
        with_word = f"{base} ({word})"
        if len(with_word) <= _ROW_TITLE:
            return with_word
    return base[:_ROW_TITLE]


def is_add_new(option: str) -> bool:
    return option == ADD_IT or option.startswith(ADD_NEW) or option.startswith("➕ Add new: ")


#: A typed "add it" to "Add it as a new material?" (request 159: "Add Tmt steel bars
#: material" and "TMT steel" were not read as the answer, live 30 Oct).
_ADD_WORDS = frozenset(
    "add yes y ok okay sheri shari athe venam cheyyu cheyy aakku akku haan ha haa ചേർക്കൂ ചേർക്ക് ശരി അതെ വേണം जोड़ो हाँ".split()
)
_NO_WORDS = frozenset("no venda vendaa illa nahi नहीं वेणा വേണ്ട ഇല്ല".split())
#: "it's a new one": "new / puthiya / vere type / save it as just കല്ല്" picks the add
#: option (request 163/165: a typed way out of the "same as ...?" question).
_NEW_WORDS = frozenset(
    "new puthiya puthu puthiyathu vere different separate another save just only "
    "പുതിയ പുതിയത് വേറെ വേറൊരു".split()
)


def typed_new_material_answer(text: str, name: str, options: list[str]) -> str | None:
    """The option a typed reply picks for the new-material question: a listed
    material it names, "No", or the add option when it says add / yes or repeats
    the material's own name ("TMT steel" for "Tmt steel bars"). None when it is
    something else (a new update): the model reads it then."""
    from .draft_answer import MAX_ANSWER_WORDS, _plain, option_answer

    said = _plain(text)
    if not said or len(said) > MAX_ANSWER_WORDS:
        return None
    adds = [o for o in options if is_add_new(o)]
    listed = [o for o in options if not is_add_new(o) and o != "No"]
    if set(said) <= _NO_WORDS:
        return "No" if "No" in options else None
    rest = [w for w in said if w not in _ADD_WORDS and w not in _FILLER and w not in _NEW_WORDS]
    for words in (text, " ".join(rest)):
        picked = option_answer(words, listed) if listed and words else None
        if picked is not None:
            return picked
    wants_new = said[0] in _ADD_WORDS or bool(rest) or bool(set(said) & _NEW_WORDS)
    if adds and wants_new and set(rest) <= set(_plain(name)) | set(_plain(" ".join(adds))):
        return adds[0]
    return None


_FILLER = frozenset({"material", "new", "it", "list", "the", "to", "as", "a", "s", "type", "alla", "അല്ല"})
#: WhatsApp lists hold ten rows: nine materials and "Something else".
LIST_MATERIALS = 9


@dataclass(slots=True)
class MaterialEntry(EntryScope):
    context_resolver: Any
    catalog_query: Any
    inventory_query: Any | None
    org_settings_query: Any | None
    actor: Any
    #: The sender's active project/site (``ContextResolver`` reads it).
    active_context: Any | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        """The workflow to start, a line to say, or None (use the classic route)."""
        fields = dict(candidate.fields)
        direction = fields.get("direction")
        if direction not in _BY_DIRECTION:
            return None
        event_type, workflow_key = _BY_DIRECTION[direction]
        quantity = number(fields.get("quantity"))
        if quantity is None or quantity <= 0 or not fields.get("material_name"):
            return Say("error", "Not saved: the material and a quantity above zero are needed.")
        fields["quantity"] = quantity

        opening = direction == "opening_stock"
        if opening and not role_can_adjust(str(getattr(self.actor, "role", "") or "")):
            # The web's rule (BE-12): stock that changes without a delivery behind it.
            return Say(
                "info",
                "Not saved: opening stock can only be entered by an admin or project manager.",
            )
        transfer = direction == "transfer"
        to_name = str(fields.pop("to_site_name", "") or "").strip()

        scoped = await self.settle(message, understanding, candidate, module=_MODULE, site_required=transfer)
        if isinstance(scoped, Say):
            return scoped
        ctx, organization_id = scoped.ctx, scoped.organization_id
        project_id, site_id = scoped.project_id, scoped.site_id
        destination: dict[str, Any] = {}
        if transfer:
            placed = self._destination(scoped, to_name)
            if isinstance(placed, Say):
                return placed
            destination = placed

        found = await self._material(organization_id, str(fields["material_name"]), fields, ctx, message)
        if not isinstance(found, dict):
            return found
        material = found
        fields.pop("new_material", None)
        fields.pop("name_en", None)
        fields["material_id"] = str(material["id"])
        fields["material_name"] = material["name"]

        fit = await fit_stock_unit(
            fields,
            material,
            catalog_query=self.catalog_query,
            organization_id=organization_id,
            correlation_id=message.correlation_id,
        )
        if fit.kind == "mismatch":
            role = getattr(self.actor, "role", None)
            text = ask_amount_text(material, fields, fit, role=role)
            ask = conversion_question(material, fit, role=role)
            if ask is None:
                # Request 129: still a line of the draft card, with the question
                # beside it ("Steel used: 20 rod (❓ How many kg is 20 rod?)"), not
                # only the model's words; a typed amount in the stock unit fills it.
                return Say(
                    "info",
                    text,
                    question=amount_question(fields, fit),
                    awaiting=AWAIT_AMOUNT,
                    answer_unit=stock_unit_code(fit),
                )
            question, options = ask
            return Say(
                "choose",
                f"{text} The question is shown to them"
                + (f" with buttons {' / '.join(options)}" if options else "")
                + f': "{question}". When they answer with a number, call set_unit_conversion '
                "(unit_amount 1, stock_amount that number), then this tool again with their original "
                "amount and unit. If they pick Other, ask them the number (ask_user, no options).",
                question=question,
                options=options,
                awaiting=AWAIT_UNIT,
            )

        site_name = self._site_name(site_id)
        if transfer:
            fields.update(destination)
            fields["from_site_name"] = site_name
        elif opening:
            fields["movement_reason"] = OPENING_STOCK
            fields["direction"] = "received"
            fields["site_label"] = site_name
        for key in SCOPE_KEYS:
            fields.pop(key, None)
        # The card's rule: a blank or default "UTC" zone is India, so a 2:45 AM
        # entry lands on today, not yesterday (22 Oct).
        fields = resolve_occurred_date(fields, timezone_name=str(company_zone(ctx.timezone)))
        if direction == "used":
            stock = await self._stock(organization_id, project_id, site_id, fields["material_id"], message)
            if stock is not None:
                fields["available_stock"] = stock
                if float(fields["quantity"]) > float(stock) and not await self._has_opening(organization_id, site_id, fields, message):
                    # [103]: used more than the book says and no starting stock was
                    # ever entered: the warning points at "opening stock".
                    fields["no_opening_stock"] = True

        return self.ready(scoped, message, event_type, workflow_key, fields)

    def _site_name(self, site_id: Any) -> str:
        for site in getattr(self.actor, "sites", None) or []:
            if str(site.id) == str(site_id):
                return str(site.name)
        return ""

    def _destination(self, scoped: Any, said: str) -> dict[str, Any] | Say:
        """The site it went to, only ever one of the sender's own sites (their
        company's, by the same list the pickers use); anything else is asked
        as a list, never guessed."""
        sites = list(getattr(self.actor, "sites", None) or [])
        projects = {str(p.id): str(p.name) for p in getattr(self.actor, "projects", None) or []}
        others = [s for s in sites if str(s.id) != str(scoped.site_id)]
        names = [str(s.name) for s in sites]
        # Two sites with one name are told apart by their project.
        labels = {
            str(s.id): (
                f"{s.name} ({projects.get(str(s.project_id), '')})"
                if names.count(str(s.name)) > 1 and projects.get(str(s.project_id))
                else str(s.name)
            )
            for s in sites
        }
        key = " ".join(said.casefold().split())
        hit = [s for s in others if key and " ".join(labels[str(s.id)].casefold().split()) == key]
        if not hit and key:
            hit = [s for s in others if " ".join(str(s.name).casefold().split()) == key]
        if not hit and key:
            # The same matcher as the source and every other line (partial names:
            # "Green Villa" for "Green Villa, Kakkanad"); several hits stay a question.
            from .site_match import find_sites, mentioned_sites

            hit = find_sites(others, said, projects, part=True) or mentioned_sites(others, said)
        if len(hit) != 1:
            if not others:
                return Say("info", "Not saved: you have no other site to send it to. Your admin can add one.")
            question = "Which site did it go to?" if not said else f'"{said}" isn\'t one of your sites. Which site did it go to?'
            return choose(question, [labels[str(s.id)] for s in others], "to_site")
        site = hit[0]
        return {
            "to_site_id": str(site.id),
            "to_project_id": str(site.project_id),
            "to_site_name": str(site.name),
        }

    async def _has_opening(self, organization_id: str, site_id: Any, fields: dict, message: Any) -> bool:
        """Whether opening stock was ever entered for this material here. A
        failed lookup says yes: the hint is never worth a wrong line."""
        check = getattr(self.catalog_query, "has_opening_stock", None)
        if check is None:
            return True
        try:
            return bool(
                await check(
                    organization_id=organization_id,
                    site_id=str(site_id) if site_id else None,
                    material_id=str(fields["material_id"]),
                )
            )
        except Exception:  # noqa: BLE001
            _log.warning("material_entry.opening_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return True

    async def _pick_material(self, organization_id: str, question: str, name: str, note: str = "") -> Say:
        """The material to choose from. A company with more than ten materials
        gets the nine closest to what was typed (recent use first) and
        "Something else": a WhatsApp list holds ten rows, and the first ten
        alphabetically was all anyone saw."""
        listed: list[dict] = []
        total = 0
        try:
            closest = getattr(self.catalog_query, "closest_materials", None)
            if closest is not None:
                listed, total = await closest(organization_id=organization_id, name=name, limit=LIST_MATERIALS)
            else:
                listed = await self.catalog_query.list_active_materials(organization_id=organization_id)
                total = len(listed)
        except Exception:  # noqa: BLE001
            listed = []
        if not listed:
            return Say(
                "info",
                f'Not saved: "{name}" is not in the material list, and the list is empty. An admin adds materials on the dashboard.',
            )
        names = [m["name"] for m in listed]
        if total > len(names) or total > 10:
            names = names[:LIST_MATERIALS] + [SOMETHING_ELSE]
            note += (
                f' If they pick "{SOMETHING_ELSE}", ask them to type the material name (ask_user, '
                "no options), then call this tool again with what they typed."
            )
        return choose(question, names, "material", note=note)

    async def _material(
        self, organization_id: str, name: str, fields: dict, ctx: Any, message: Any
    ) -> dict | Say | None:
        """The catalogue row, a question for the model to ask (ARCH-04: the
        old picker buttons, as the model's own question), or None when the
        lookup failed (the classic route answers)."""
        from workflows.entities import Ambiguous, Resolved

        said = name
        named = english_name(said, fields.get("name_en"))
        try:
            matches = await self._find(organization_id, said)
            by_word = False
            if not matches:
                matches = await self._by_word(organization_id, said, named)
                by_word = bool(matches)
        except Exception:  # noqa: BLE001 -- the classic route asks or lets it through
            _log.warning("material_entry.lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return None
        # A word this company taught, or a known local word, names one material exactly.
        outcome = Resolved(str(matches[0]["id"]), str(matches[0]["name"])) if by_word else classify_material_matches(name, matches)
        if isinstance(outcome, Resolved):
            material = next(m for m in matches if str(m["id"]) == outcome.entity_id)
            if not material.get("is_active", True):
                return Say("info", f"Not saved: {material['name']} is no longer in use in the material list.")
            return material
        if isinstance(outcome, Ambiguous):
            names = [c.display_name for c in outcome.candidates]
            if len(names) > 10:
                return await self._pick_material(organization_id, f'Which material is "{name}"?', name)
            return choose(f'Which material is "{name}"?', names, "material")

        if getattr(message, "modality", None) in (InputModality.IMAGE, InputModality.DOCUMENT):
            # A bill's trade name ("Cement OPC 53 grade", "TMT steel bars 12mm",
            # "Wire cut bricks"): the one listed material it names (live photo
            # set, 22 Oct: told to give the plain name, the model still passed
            # the bill's). Only for what was read from a bill; typed words ask.
            named = await self._named_on_bill(organization_id, name, message)
            if named is not None:
                return named

        may_create = await self._may_create(organization_id)
        if may_create and fields.get("new_material"):
            return await self._create(organization_id, named, fields, ctx, message)
        if may_create:
            near = await self._near_duplicates(organization_id, named.name)
            add = add_new_label(named.name, said)
            ask = _name_question(named, said)
            if near:
                # Before anything is created: "Same as Steel rods?" (it runs for everyone).
                return Say(
                    "choose",
                    f'Not saved yet: "{name}" is not in the material list, but it is close to {", ".join(near)}. '
                    "Ask which one they meant. If they pick a listed material, call this tool again with that "
                    f'exact material; if they pick "{add}" (or say it is a new one), call it again with '
                    f"new_material true. {_NAME_NOTE}",
                    question=f'"{said}" isn\'t in your list. Is it the same as one of these?{ask}',
                    options=(*near, add),
                    awaiting=AWAIT_NEW_MATERIAL,
                )
            return Say(
                "choose",
                f'Not saved yet: "{name}" is not in the company\'s material list. Ask whether to add it '
                "as a new material. If yes, call this tool again with new_material true; if no, ask "
                f"which listed material they meant. {_NAME_NOTE}",
                question=f'"{said}" isn\'t in your material list yet. Add it as a new material?{ask}',
                options=(add, "No"),
                awaiting=AWAIT_NEW_MATERIAL,
            )
        return await self._pick_material(
            organization_id,
            f'"{name}" isn\'t in the material list. Which one is it?',
            name,
            note=" A new material is added by an admin on the dashboard.",
        )

    async def _near_duplicates(self, organization_id: str, name: str) -> list[str]:
        """Up to three listed materials close to ``name`` in spelling."""
        from difflib import SequenceMatcher

        try:
            closest = getattr(self.catalog_query, "closest_materials", None)
            if closest is None:
                return []
            listed, _ = await closest(organization_id=organization_id, name=name, limit=NEAR_LIMIT)
        except Exception:  # noqa: BLE001 -- no suggestion is better than a failed save
            return []
        typed = " ".join(name.casefold().split())
        near: list[str] = []
        for row in listed:
            listed_name = " ".join(str(row["name"]).casefold().split())
            if SequenceMatcher(None, typed, listed_name).ratio() >= NEAR_DUPLICATE or typed in listed_name:
                near.append(str(row["name"]))
        return near

    async def _named_on_bill(self, organization_id: str, name: str, message: Any) -> dict | None:
        """The listed material a bill line names, by its words and word pairs
        (singular or plural): the longest exact catalogue name found, when it is
        the only one that long. None when no listed name, or more than one, is in it."""
        import re

        from workflows.entities import Resolved

        words = [w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 1]
        tries: list[str] = []
        for size in (2, 1):
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i : i + size])
                tries.append(phrase)
                if phrase.endswith("s") and len(phrase) > 3:
                    tries.append(phrase[:-1])
        found: dict[str, dict] = {}
        for phrase in dict.fromkeys(tries):
            try:
                rows = await self.catalog_query.find_materials(organization_id=organization_id, name=phrase)
            except Exception:  # noqa: BLE001 -- the usual question follows
                _log.warning("material_entry.bill_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
                return None
            for row in rows:
                if isinstance(classify_material_matches(phrase, [row]), Resolved) and row.get("is_active", True):
                    found[str(row["id"])] = row
        if not found:
            return None
        longest = max(len(str(r["name"]).split()) for r in found.values())
        best = [r for r in found.values() if len(str(r["name"]).split()) == longest]
        if len(best) != 1:
            return None
        _log.info("material_entry.bill_name correlation_id=%s matched=%s", message.correlation_id, best[0]["name"])
        return best[0]

    async def _may_create(self, organization_id: str) -> bool:
        """STA-139's rule: the org's whatsapp_material_create_roles setting."""
        from types import SimpleNamespace

        from runtime.inbound_journey.seeding import _may_create_material

        try:
            return await _may_create_material(
                SimpleNamespace(organization_id=organization_id),
                actor_role=getattr(self.actor, "role", None),
                org_settings_query=self.org_settings_query,
            )
        except Exception:  # noqa: BLE001 -- unknown rights never grant
            _log.warning("material_entry.create_rights_failed", exc_info=True)
            return False

    async def _find(self, organization_id: str, name: str) -> list[dict]:
        """Catalogue matches for a name, with "bricks" finding "Brick" (review, 22 Oct)."""
        matches = await self.catalog_query.find_materials(organization_id=organization_id, name=name)
        singular = name.strip()[:-1] if name.strip().lower().endswith("s") else ""
        if not matches and len(singular) > 2:
            matches = await self.catalog_query.find_materials(organization_id=organization_id, name=singular)
        return matches

    async def _by_word(self, organization_id: str, said: str, named: EnglishName) -> list[dict]:
        """The material a word stands for when its own letters found nothing: the
        word this company already taught (the alias store), then the English name of
        a known local word ("സിമന്റ്" -> Cement). Only an exact English name counts:
        കല്ല് (Stone) must never land on Laterite stone."""
        by_alias = getattr(self.catalog_query, "find_by_alias", None)
        if by_alias is not None:
            hit = await by_alias(organization_id=organization_id, alias=said)
            if hit is not None:
                return [hit]
        if named.name.casefold() == " ".join(said.casefold().split()):
            return []
        wanted = {named.name.casefold(), named.name.casefold().rstrip("s")}
        exact = [m for m in await self._find(organization_id, named.name) if str(m["name"]).casefold() in wanted
                 or str(m["name"]).casefold().rstrip("s") in wanted]
        return exact if len(exact) == 1 else []

    async def _create(self, organization_id: str, named: EnglishName, fields: dict, ctx: Any, message: Any) -> dict | Say:
        """Add the material (the sender said yes), counted in the unit they used.
        Saved under its English name; their own word is kept as an alias."""
        name = named.name
        unit_text = fields.get("unit")
        unit = await self.catalog_query.resolve_unit(str(unit_text)) if unit_text else None
        if unit is None:
            return Say(
                "choose",
                f'Not saved yet: which unit is "{name}" counted in? Ask, then call this tool again with '
                "new_material true and that unit.",
                question=f'Which unit is "{name}" counted in?',
                options=("Bags", "Kg", "Nos", "Cum", "Cft", "Tons", "Litres", "Load"),
            )
        created = await self.catalog_query.create_material(
            organization_id=organization_id, name=name, unit_id=str(unit["id"]), created_by=str(getattr(self.actor, "user_id", None) or ctx.user_id)
        )
        if created is None:
            return Say("error", f'Not saved: "{name}" could not be added to the material list.')
        _log.info("material_entry.material_created correlation_id=%s", message.correlation_id)
        await self._remember_word(organization_id, created, named, ctx)
        return created

    async def _remember_word(self, organization_id: str, material: dict, named: EnglishName, ctx: Any) -> None:
        """Their word is an alias of the material, so it finds it next time. Never blocks the save."""
        add = getattr(self.catalog_query, "add_alias", None)
        if add is None or not named.said or alias_key(named.said) == alias_key(str(material["name"])):
            return
        try:
            await add(
                organization_id=organization_id,
                material_id=str(material["id"]),
                alias=named.said,
                created_by=str(getattr(self.actor, "user_id", None) or ctx.user_id),
            )
        except Exception:  # noqa: BLE001 -- the word is a convenience
            _log.warning("material_entry.alias_failed", exc_info=True)

    async def _stock(
        self, organization_id: str, project_id: Any, site_id: Any, material_id: str, message: Any
    ) -> float | None:
        if self.inventory_query is None:
            return None
        try:
            levels = await self.inventory_query.query(
                organization_id=organization_id,
                project_id=str(project_id) if project_id else None,
                site_id=str(site_id) if site_id else None,
                material_name=None,
                material_id=material_id,
                # WA-77: the hint compares with what was reported, saved or not.
                include_unsaved=True,
            )
        except Exception:  # noqa: BLE001 -- the stock note is a hint, never a block
            _log.warning("material_entry.stock_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return None
        return levels[0]["current_stock"] if levels else None

