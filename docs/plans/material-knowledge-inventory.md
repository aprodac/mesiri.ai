# Material knowledge inventory: TMT and M-sand (for review by a civil engineer)

> What Mesiri should know, like a good data-entry clerk on a Kerala site, before it records TMT and M-sand.
> Each fact has a source and a "review" box. Wrong facts here become wrong for every company, so **please mark each
> row ✅ / ❌ / correction**. Design: [ADR-material-knowledge.md](../architecture/ADR-material-knowledge.md).
> Written 7 Nov 2026 from web research; not yet reviewed.

## 1. Unit facts (exact, every company)

| Fact | Source | Review |
|---|---|---|
| 1 ton (tonne, MT) = 1000 kg | SI | |
| 1 cum (m³) = 35.3147 cft | SI | |
| 1 brass = 100 cft = 2.83168 m³ | Indian trade unit (Infralens, BuildingNeeds) | |
| 1 sqm = 10.7639 sqft | SI | |
| Cement bag = 50 kg | IS 269 packing | |

## 2. TMT steel bars

| Fact | Source | Review |
|---|---|---|
| Bought and billed by weight (kg / ton / quintal); delivered and used as counted bars; bundle charts give both (pcs and kg) | SteelonCall, Sree Metaliks | |
| Sizes: 8, 10, 12, 16, 20, 25, 32 mm (6 mm sometimes) | IS 1786 sizes | |
| Standard length 12 m | manufacturer charts | |
| Weight per metre = D²/162 kg (D in mm; exact constant 162.2 from 7850 kg/m³) | IS 1786; Tata Nexarc, Infralens | |
| 12 m bar: 8 mm 4.74 kg · 10 mm 7.41 · 12 mm 10.67 · 16 mm 18.96 · 20 mm 29.6 · 25 mm 46.3 · 32 mm 75.9 | computed from the formula | |
| Actual bars vary within IS tolerance; the bill / weighbridge slip is the real weight; the formula is a cross-check | SteelonCall | |
| Site words: kambi, കമ്പി, rod, bar, TMT, Fe500 / Fe500D / Fe550 | site usage | |
| **Question for review:** do your sites keep TMT stock in kg, in nos per size, or both? Proposal: record what was said, show both. | | |

**Plausible (for checks only):** one bar 3-80 kg; with the size known, within ±10% of D²/162 × 12.

## 3. M-sand (and P-sand, river sand)

| Fact | Source | Review |
|---|---|---|
| Sold per load, per cft, per brass (100 cft) or per ton | Kerala Kaumudi, Infralens (Thrissur per-ton rate) | |
| **A "load" has no standard size**: it is what that supplier's lorry carries | supplier listings | |
| Kerala example: 150 cft loads (Kottayam supplier) | Kolo listing | |
| Tamil Nadu tippers: 400-500 cft a trip | BuildingNeeds (Chennai) | |
| Lorries carry about 10-15 tonnes of sand | Hindustan Times, TN lorry federation (2018) | |
| P-sand (plastering sand) is finer M-sand, bought the same way | site usage | |
| Site words: M sand, msand, എം സാൻഡ്, P sand, manal, മണൽ, "oru load" | site usage | |
| **Question for review:** what is a usual M-sand load in cft at your sites? | | |

**Plausible (for checks only):** one load 50-600 cft (about 1.4-17 m³). One bag of sand on site about 0.025-0.05 m³.

## Sources

- [Infralens: rebar weight chart, IS 1786](https://infralens.in/knowledge/rebar-weight-chart-is-1786)
- [Tata Nexarc: unit weight of steel bars](https://blog.tatanexarc.com/da/how-to-calculate-the-unit-weight-of-steel-bars/)
- [SteelonCall: steel unit weight / procurement guide](https://steeloncall.com/blog/tmt-rod-weight-measurement-guide)
- [Sree Metaliks: TMT sizes and bundles](https://sreemetaliks.com/blog/tmt-steel-bar-sizes-and-bundle-details)
- [Kolo: Kottayam supplier, 150 CFT M-sand](https://koloapp.in/kerala/building-suppliers/ashwin-babu-1--kottayam/posts/1629322660)
- [BuildingNeeds: Chennai tipper 400-500 CFT](https://v219-4at.pages.dev/msand-price-chennai/)
- [Infralens: Thrissur sand and aggregate rates](https://infralens.in/prices/aggregates/thrissur)
- [Kerala Kaumudi: material price rise (M-sand per cft)](https://keralakaumudi.com/en/kerala/general/construction-material-price-rise-kerala-1808206)
- [Hindustan Times: lorry sand capacity (2018)](https://www.pressreader.com/india/hindustan-times-st-mumbai/20180714/281947428621835)
