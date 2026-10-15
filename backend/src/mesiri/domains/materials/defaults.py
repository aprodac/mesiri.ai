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
