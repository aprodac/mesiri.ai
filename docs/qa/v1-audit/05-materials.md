# 05 · Materials — V1 audit

9 problems found in Materials; the biggest was that a transfer between sites, which V1
promises on WhatsApp, had no way to be recorded.

> **Retest first:** commit `6ac60542` (WA-63, pushed 24 Oct after this audit) adds a
> `transfer_material` tool, a `save_opening_stock` tool, "nine closest + Something else"
> for long material lists, and Cft / Tons / Load in the unit question. MAT-01, MAT-02,
> MAT-04 and MAT-05 may now be fixed: retest before working on them.

- **Audited:** 24 Oct 2026 (before WA-63) · **Original sheet:** [Materials — WhatsApp test sheet](https://claude.ai/artifact/JPgByeLT3PJm7sMu9GjabR)
- **Main code:** `apps/whatsapp-assistant/src/runtime/agent/material_entry.py`,
  `apps/whatsapp-assistant/src/workflows/material/`, backend `backend/src/mesiri/application/materials/`.

## Summary

| ID | Problem | Severity | Approval | Status |
| --- | --- | --- | --- | --- |
| MAT-01 | No way to record a transfer between sites | Serious | None | Retest (WA-63) |
| MAT-02 | "More than the 0 in stock" on every usage when opening stock was never entered | Serious | None | Retest (WA-63) |
| MAT-03 | Day questions can't be answered ("cement used today?") | Serious | None | Known: WA-42 |
| MAT-04 | An unknown material shows only 10 choices | Other | None | Retest (WA-63) |
| MAT-05 | New-material units miss cft, load, tons | Other | None | Retest (WA-63) |
| MAT-06 | Engineers must convert units themselves | Other | None | Open |
| MAT-07 | An extra "Received or used?" on a clear message | Other | None | Needs live AI |
| MAT-08 | A question without buttons | Other | None | Open |
| MAT-09 | Bill photos lost on restart | Other | Ops (INF-09) | Open |

## Before you test

Use a **Site Engineer** number with **two sites** (Site A, Site B). MAT-01 and MAT-04 need both.

- MAT-02 needs a material with **no opening stock** (e.g. a newly added one). Leave its stock at 0.
- Tap **Save** on every card.
- Check stock on the dashboard **Materials** page after each test, for **both** sites.

## Problems

### MAT-01 · No way to record a transfer between sites

- **Severity:** Serious · **Approval:** None · **Status:** retest after WA-63
- **Repro:** `now at Site A`, then `sent 10 bags cement to Site B`
- **Actual (before WA-63):** Mesiri either says it can't, records it as **used** at Site A (Site B never receives it), or tries a **money** transfer. Check both sites' stock.

### MAT-02 · Every usage warned when opening stock was never entered

- **Severity:** Serious · **Approval:** None · **Status:** retest after WA-63
- **Repro:** with a material at 0 stock: `18 bags cement used for slab`
- **Actual (before WA-63):** "That's more than the 0 bags in stock, so it's flagged on tonight's report", every time; there was no WhatsApp way to enter opening stock.

### MAT-03 · Day questions can't be answered

- **Severity:** Serious · **Approval:** None · **Status:** known, tracker WA-42
- **Repro:** after today's entries: `how much cement was used today?`, then `cement received yesterday?`
- **Actual:** Mesiri says it only sees totals so far.

### MAT-04 · An unknown material shows only 10 choices

- **Severity:** Other · **Approval:** None · **Status:** retest after WA-63
- **Repro:** company with 15+ materials; as an engineer: `20 bags white cement came`
- **Actual (before WA-63):** the list offers only 10 materials; the right one may be missing.

### MAT-05 · New-material units miss cft, load, tons

- **Severity:** Other · **Approval:** None · **Status:** retest after WA-63
- **Repro:** as an admin: `5 load M sand came` → Yes, add it
- **Actual (before WA-63):** the unit choice is only Bags, Kg, Nos, Cum, Litres.

### MAT-06 · Engineers must convert units themselves

- **Severity:** Other · **Approval:** None
- **Repro:** sand counted in m³; as an engineer: `2 loads sand came`
- **Actual:** Mesiri asks "How much is that in Cubic Meters?", which a site worker can't easily answer.

### MAT-07 · An extra question on a clear message

- **Severity:** Other · **Approval:** None · **Needs live AI**
- **Repro:** `50 bags cement arrived` (repeat 4 times)
- **Actual:** sometimes it still asks "Received or used?" (2 of 4 in the team's live runs).

### MAT-08 · A question without buttons

- **Severity:** Other · **Approval:** None
- **Repro:** `cement vannu`
- **Actual:** the question comes as plain text, no tap options.

### MAT-09 · Bill photos lost on restart

- **Severity:** Other · **Approval:** Ops (INF-09)
- **Repro:** send a cement bill, tap **Material Delivery**, Save; check after the next deploy.
- **Actual:** the bill photo no longer opens. (Also see PHO-03: the bill photo isn't attached to the receipt at all.)

## Already works

Plural names (`bricks` finds Brick); a bill's trade name (`OPC 53 grade`) finds Cement;
Cancel takes the stock movement back; different units are never added together; usage
above stock is saved and flagged rather than refused.

## Test results

| ID | Problem | Result | What Mesiri replied, or the stock after |
| --- | --- | --- | --- |
| MAT-01 | No transfer between sites | Not tested | |
| MAT-02 | Zero-stock warning every time | Not tested | |
| MAT-03 | Day questions unanswered | Fixed (tests) | "Yesterday (24 Oct): 10 bags cement used. 535 bags left now." from material_movements by project-zone day; today / this week too. |
| MAT-04 | Only 10 material choices | Not tested | |
| MAT-05 | New material units incomplete | Not tested | |
| MAT-06 | Engineers convert units | Fixed (test) | Admin stores 1 load = 4 cum; engineer's "2 loads sand" saves 8 cum with no question; before it, the question says "cum". Long buttons no longer cut ("The amount in cubic"); old questions close. |
| MAT-07 | Extra "Received or used?" | Fixed (tests, prompt part not run live) | Code refuses "Received or used?" and a "used" save for arrived/came/vannu messages. |
| MAT-08 | Question without buttons | Fixed (tests) | ask_user with no options gets Received/Used or 10/25/50/Other. |
| MAT-09 | Bill photos lost on restart | Not tested | |
