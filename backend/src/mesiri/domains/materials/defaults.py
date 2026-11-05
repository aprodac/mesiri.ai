"""Starter materials every new company gets (BE-24).

Only an ADMIN or PROJECT_MANAGER may add a material from WhatsApp
(`whatsapp_material_create_roles`), so a company with an empty catalogue
answers its site supervisor's first "40 bags cement" with "ask your admin".
These rows make the first day's updates go through.

Names are the plain words sites use, because WhatsApp only resolves a
material silently on an exact (case-insensitive) name match; a partial match
asks with a picker. So one row per material, no size variants, except
aggregate, where the size is what gets ordered. Spelled the way it is
usually typed ("M Sand", not "M-Sand"): punctuation is part of the name.

Unit codes must exist in `units_of_measure` (platform-wide). Sand and
aggregate are in `cum` until `cft`/`load` exist (BE-39). Seeded rows are
ordinary catalogue rows; a company can rename or deactivate any of them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StarterMaterial:
    name: str
    unit_code: str
    category: str


STARTER_MATERIALS: tuple[StarterMaterial, ...] = (
    StarterMaterial("Cement", "bags", "Masonry"),
    StarterMaterial("Sand", "cum", "Masonry"),
    StarterMaterial("M Sand", "cum", "Masonry"),
    StarterMaterial("P Sand", "cum", "Masonry"),
    StarterMaterial("Aggregate 20mm", "cum", "Concrete"),
    StarterMaterial("Aggregate 40mm", "cum", "Concrete"),
    StarterMaterial("RMC", "cum", "Concrete"),
    StarterMaterial("Steel", "kg", "Steel"),
    StarterMaterial("Binding Wire", "kg", "Steel"),
    StarterMaterial("Bricks", "nos", "Masonry"),
    StarterMaterial("Solid Blocks", "nos", "Masonry"),
    StarterMaterial("Laterite Stone", "nos", "Masonry"),
    StarterMaterial("Plywood", "nos", "Shuttering"),
    StarterMaterial("Tiles", "sqft", "Finishing"),
    StarterMaterial("Paint", "litres", "Finishing"),
    StarterMaterial("Wall Putty", "bags", "Finishing"),
    StarterMaterial("Waterproofing Compound", "litres", "Finishing"),
    StarterMaterial("PVC Pipe", "nos", "Plumbing"),
    StarterMaterial("Electrical Wire", "rolls", "Electrical"),
)


# [254] (5 Nov, Adarsh: "10 bags metal came" made "Metal" a new material): the words sites use for the starter
# materials, said in English letters. "metal" / "jelly" IS aggregate in Kerala; plain "metal" is either size, so it
# names both and the person picks. A trade name matches a whole word said ("metal"), never a word inside a longer
# name ("metal sheet", "baby metal" are not aggregate). Only names the company still has are offered.
TRADE_NAMES: dict[str, tuple[str, ...]] = {
    "Aggregate 20mm": ("metal", "jelly", "chips", "20mm metal", "metal 20mm", "20mm jelly", "jelly 20mm",
                       "20mm aggregate", "3/4 metal", "three fourth metal"),
    "Aggregate 40mm": ("metal", "jelly", "chips", "40mm metal", "metal 40mm", "40mm jelly", "jelly 40mm",
                       "40mm aggregate", "1 1/2 metal"),
    "M Sand": ("msand", "manufactured sand", "crusher sand"),
    "P Sand": ("psand", "plastering sand", "plaster sand"),
    "Steel": ("kambi", "tmt", "tmt bar", "tmt bars", "tmt steel", "rod", "rods", "steel rod", "steel rods"),
    "Solid Blocks": ("solid block", "concrete block", "concrete blocks", "cement block", "cement blocks"),
    "Laterite Stone": ("chenkallu", "chenkal", "vettukallu"),
    "Bricks": ("ishtika", "ishtik"),
}


def trade_key(text: str) -> str:
    """How a trade name is compared: lower case, letters, digits and "/" only ("M-Sand", "m sand" -> "msand")."""
    return "".join(c for c in (text or "").casefold() if c.isalnum() or c == "/")


_BY_TRADE: dict[str, tuple[str, ...]] = {}
for _material, _words in TRADE_NAMES.items():
    for _word in _words:
        _BY_TRADE[trade_key(_word)] = (*_BY_TRADE.get(trade_key(_word), ()), _material)


def trade_name_of(said: str) -> tuple[str, ...]:
    """[254]: the starter materials ``said`` is a trade name of ("metal" -> both aggregates), or ()."""
    return _BY_TRADE.get(trade_key(said), ())

