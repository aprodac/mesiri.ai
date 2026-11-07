# ADR: Material knowledge as data, one resolver (TMT and M-sand first)

> Status: **proposed** by Claude, 7 Nov 2026; asked for by Ilan ("write the design and start with TMT and
> M-sand", "let's not go for hardcoded solutions"). Slice 1 (below) is additive and was started on Ilan's go.
> **Needs Alan's review**: the resolver becomes a shared component (dashboard + WhatsApp), and change C3 alters a
> rule Alan approved on 3 Nov ([units-and-sizes.md](units-and-sizes.md) rule 4).
> Extends [units-and-sizes.md](units-and-sizes.md); fits [assistant-v3.md](assistant-v3.md) (a business rule lives
> in the API); not an architecture change.

## Why

**Evidence (production, 31 Oct - 7 Nov):**

- 41 of 124 v3 material save calls (33%) were refused by the code's own checks and sent back to the model:
  "'സിമന്റ്' is not in the company's material list", "'TMT Steel Bars' ... (nearest: Steel)", "material_said is not
  in English", "say which material they named" (`scripts/friction_report.py`, tool errors).
- Customers needed 6-7 messages and taps per saved entry (target 2).
- 96 TMT / M-sand messages read one by one:
  - "how many kg is one rod?" asked 6+ times; site people count rods, the weight follows from the size.
  - impossible sizes were saved: New India "1 load M-sand = 60 cum" (about 2,100 cft, four-plus tippers);
    test company "20 TMT bars = 1 ton" (50 kg a bar; a 12 mm bar is ~10.7 kg).
  - one material in three items ("Steel", "TMT steel bars", "Rod steel"), so stock split and went negative.
  - "oru load ethra aanennu enikku ariyilla" (31 Oct), "🤷 Ariyilla" (cd, 6 Nov): the site cannot know a load's size;
    the line was then held until an admin answered.

**Mechanism.** The knowledge a site clerk carries has no home. It is spread over:

| Where | What | Problem |
|---|---|---|
| `domains/materials/unit_conversion.py` | `_FIXED` (kg/ton, cft/cum, brass), `CEMENT_BAG_KG`, `BAR_LENGTH_M` + D²/162 (only when the name says "12mm"), `_NATURAL` regex word lists (kambi, manal, ഇഷ്ടിക...) | facts and words in code; a new word or size needs a deploy |
| `agent_api/materials.py` | resolver with one branch per past request ([210], [217], [232], [243], [248], [254], [268]); translation hints in the model's instructions ("manal = Sand, kambi = Steel") | patches; the model picks, the code refuses, the model retries (the 33%) |
| `materials/defaults.py` | starter list, units in code | "Sand ... in cum until cft/load exist" |
| nowhere | what is plausible (a load, a bar's weight) | anything a person types is saved |

## Decision

Split the work by what each part is good at:

- **The model understands**: language, what was meant, quantities, mixed messages. It translates Malayalam and
  Manglish well (every word in the 96 messages was understood). No big word lists.
- **Data holds the knowledge**, in three layers, each fact with its source.
- **One resolver in the backend API decides** (material, size, conversion, plausibility, at most one question), used by
  WhatsApp and the dashboard alike. The code knows *how* to apply a rule; the numbers are rows.

### The three layers

**A. Trade reference (platform-wide, reviewed by a civil engineer, editable in the control panel).** Small; grows from
what real messages need, not a model of all construction.

| Table | Holds | Seeded with (slice 1 in bold) |
|---|---|---|
| `ref_unit_facts` | exact conversions between units | **kg/ton, cft/cum, cft/brass, cum/brass, sqft/sqm** (today's `_FIXED`) |
| `ref_material_kinds` | a kind of material, its natural stock unit, the words that name it, a mass rule | **TMT bar** (kg; round bar D²/162 kg/m, 12 m), **M-sand / P-sand / sand** (cft); cement (bags, 50 kg), bricks, aggregate later |
| `ref_kind_ranges` | what is plausible: one `from_unit` of a kind in its stock unit, min..max | **M-sand load 50-600 cft; TMT bar 3-80 kg per piece (±10% of D²/162×12 when the size is known)** |

Sources recorded on each row: IS 1786 (bar mass), supplier practice (Kerala 150 cft loads; Tamil Nadu tippers
400-500 cft), unit definitions (1 brass = 100 cft = 2.83 m³).

**B. Company knowledge (per company; mostly existing tables).** The company's word wins over the reference.

| Existing | Added |
|---|---|
| `materials_catalog` (their items), `material_aliases` (their words), `material_unit_conversions` (their sizes) | `materials_catalog.kind` (link to A) and `size_mm` (TMT variants as items: "TMT 8 mm", "TMT 12 mm"); `material_unit_conversions.source` (person / bill / GRN / reference) |

**C. Behaviour (SOP + code checks), changed:**

1. **C1 Never ask what the code can work out.** A TMT bar's weight comes from its size (A); the only TMT question is
   the size, with the company's own sizes as buttons, remembered per site.
2. **C2 Refuse the impossible, politely, with the plausible range** (A ranges): "1 load = 60 cum is about 2,100 cft;
   a load is usually 100-600 cft. How many cft?" Never silently saved.
3. **C3 Save what was said; a missing size never holds a line** (*changes units-and-sizes rule 4; needs Alan*). "3
   load M-sand" saves 3 loads; stock shows "3 loads" until the company's load size is known (from setup, a bill, a
   GRN or an admin), then converts. Today the line is held on a size request.
4. **C4 Learn once.** Every confirmation, correction or bill writes to B with its source; the same question is never
   asked twice.

### Initial data, frictionless

Most of B comes before anyone is asked:

1. **From documents they already have**: last month's bills, the BOQ, a PO, the stock register (photo / Excel). Mesiri
   reads them (bill reading exists for expenses) and proposes: their items and sizes ("TMT 8/10/12 mm Fe500"), real
   conversions ("2.0 t, 188 nos"), load sizes ("150 cft"), vendors, rates, opening stock. One review, one tap.
2. **A 5-minute setup in taps**: "Which do you use? [Cement] [TMT 8] [TMT 10] [TMT 12] [M-sand] ..." (builds on the
   onboarding fast path, [24]).
3. **The rest is learned as they go** (C4), one question the first time, with buttons.

### One resolver

`POST /materials/resolve` (backend; dashboard and v3 tool): in `{said, quantity, unit_said, site_id}`, out
`{material_id, kind, size_mm, quantity, unit, in_stock_unit | null, plausible, confidence, question | null}`. It reads A
and B; `unit_conversion.py`'s public functions keep their signatures and read A instead of constants, so classic and
every existing caller is unchanged. `agent_api/materials.py`'s branches are deleted at switch-over.

## Rollout (each slice: tests, live checks, then the next)

| Slice | What | Behaviour change | Approval |
|---|---|---|---|
| **1** | Tables A seeded for TMT + M-sand; `PUT /materials/{id}/unit-conversions` refuses implausible sizes with the range (C2) | only impossible sizes refused (extends units-and-sizes rule 3) | Ilan (7 Nov) |
| 2 | `unit_conversion.py` reads A instead of constants (`_FIXED`, bar mass, `_NATURAL` words) | none (same answers, from data); proven by the existing tests | - |
| 3 | `materials_catalog.kind` + `size_mm`; TMT sizes as items; the size question with the company's sizes (C1) | TMT asks size, never kg | Alan (shared component) |
| 4 | Resolver in **shadow mode**: runs beside today's code on real messages, decisions compared, logged | none | Alan |
| 5 | Switch v3 + dashboard to the resolver; delete `materials.py` branches; C3 | yes | Alan |
| 6 | Initial data from documents | new | Alan |
| - | Correct the wrong rows already saved (New India load, test-company steel) | data change | Ilan, row by row |

## Risks

- **Wrong reference facts become wrong everywhere.** Every row has a source; a civil engineer reviews the seed
  ([material-knowledge-inventory.md](../plans/material-knowledge-inventory.md)); ranges are wide (they catch the
  impossible, not the unusual).
- **Replacing a patched, live resolver.** Shadow mode first; switch only when it matches or beats today on every live
  check.
- **Migrations.** Additive only (new tables, nullable columns). Correcting saved data is separate and asked first.

## Rollback

Each slice is its own commit. Slice 1: revert the commit; the tables can stay (nothing reads them).
