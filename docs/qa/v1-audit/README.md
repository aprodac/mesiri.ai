# V1 audit — WhatsApp assistant and dashboard

Pre-launch audit of every V1 feature, module by module, as a site engineer, PM or
owner would use it. Finding and documenting only: nothing here has been fixed yet.

- **Scope it was checked against:** [docs/product/V1_SCOPE.md](../../product/V1_SCOPE.md)
- **Dates:** 23–24 Oct 2026, `main` at `20bf7740` (modules 1–8) and `373d70a4` (module 9)
- **Method:** read the real code path end to end (WhatsApp message → agent tool →
  workflow → backend → DPR / dashboard), then confirm each suspected problem by running
  the real code with the exact inputs (probe scripts outside the repo).
- **Not verified anywhere:** the live AI model's wording and speed (no AI key locally),
  real WhatsApp delivery, and the PDF as Chromium draws it on the server. Rows that
  depend on what the AI chooses say so.

## Modules

| # | Module | File | Problems | Serious | Needs Alan / a decision | Original test sheet |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Setup & Team | [01-setup-team.md](01-setup-team.md) | 12 | 4 | SET-01 (security) | [sheet](https://claude.ai/artifact/TTnyiMyXvEvGz6M4G1L4Dc) |
| 2 | Sites | [02-sites.md](02-sites.md) | 15 | 4 | WA-46 still open | [sheet](https://claude.ai/artifact/DJ8nNXh2ygpAPJXf5mgqgv) |
| 3 | Attendance | [03-attendance.md](03-attendance.md) | 10 | 6 | All (Labour module) | [sheet](https://claude.ai/artifact/PytQSqceGCxsykUk2rvy7w) |
| 4 | Work done | [04-work-done.md](04-work-done.md) | 7 | 3 | — | [sheet](https://claude.ai/artifact/JGJiutqTtxzFVyd9Cbj4gC) |
| 5 | Materials | [05-materials.md](05-materials.md) | 9 | 3 | — | [sheet](https://claude.ai/artifact/JPgByeLT3PJm7sMu9GjabR) |
| 6 | Issues & Conditions | [06-issues-conditions.md](06-issues-conditions.md) | 15 | 7 | ISS-01, ISS-04 (decision) | [sheet](https://claude.ai/artifact/NejmbHH71iLXuMu2cbDqYq) |
| 7 | Photos | [07-photos.md](07-photos.md) | 10 | 5 | PHO-04, PHO-10 (Labour) | [sheet](https://claude.ai/artifact/K6cggQMG3hK7NwFQ9ee2aL) |
| 8 | DPR | [08-dpr.md](08-dpr.md) | 9 | 5 | DPR-01 (data rewrite), DPR-03/04 (decision) | [sheet](https://claude.ai/artifact/5B7zxsoAiLfmrBiN8us7VA) |
| 9 | Dashboard | [09-dashboard.md](09-dashboard.md) | 10 | 4 | DSH-02 (security), DSH-05/06 (Labour) | [sheet](https://claude.ai/artifact/N87zhBa5VB8YFaC555Pbp1) |
| | **Total** | | **97** | **41** | | |

Still to do: one full-day end-to-end check, then a single ranked list
(wrong data → lost messages → UX).

## How to use these files

Each module file has:

1. **Summary table:** ID, problem, severity, approval, main code location.
2. **One section per problem:** what the user sees, exact steps to reproduce, expected
   vs actual, where the code is, a fix direction, and how it was verified.
3. **Already works:** behaviour checked and found correct; no need to retest.
4. **Test results:** a blank table to fill in after a phone test.

Problem IDs are stable (`ISS-05`, `DPR-03`, …): use them in commits, the tracker and
chat. The `#` numbers in the original Claude Doc sheets match the ID numbers.

### Approval labels (from [CLAUDE.md](../../../CLAUDE.md))

- **Alan: Labour** — changes Labour, Attendance, Payroll or Workforce behaviour.
- **Alan: security** — auth, tokens, tenant isolation, permissions.
- **Alan: data rewrite** — a migration that rewrites existing rows.
- **Decision** — depends on an open product decision.
- **Ops** — a server or Meta task, not a code change.
- **None** — can be fixed and pushed under autonomous mode.

### Verification labels

- **Scripted run** — confirmed by running the real code with the exact inputs.
- **Code read** — found by reading the code; not run.
- **Needs live AI** — depends on what the model chooses; only a phone test can confirm.

## Cross-cutting problems (appear in several modules)

| Problem | Where it shows | Status |
| --- | --- | --- |
| Production photo storage is the in-memory fake: every photo is lost on restart | ATT-08, WRK-07, MAT-09, PHO-05 | Tracker INF-09, in progress (ops) |
| Meta message templates not approved: nobody outside the 24 h window gets the evening check or the DPR | SET-02, DPR-02 | Tracker WA-10, todo (ops) |
| "Yesterday" questions answered with today | ATT-04, WRK-03 | Same date handling in the query seeds |
| Weather, tomorrow's plan and equipment can't be entered on WhatsApp | ISS-01..03, DPR-03 | No tool and no table for equipment |
| Two DPR PDF renderers (WhatsApp HTML vs dashboard fpdf) look and behave differently | ISS-07, ISS-13, DPR-09 | `backend/src/mesiri/domains/dpr/pdf.py` vs `apps/whatsapp-assistant/src/channel/dpr_document/` |

## Related documents

- [V1 scope](../../product/V1_SCOPE.md) (from `Mesiri_V1_Scope.pdf`)
- [Codebase review, 21 Oct 2026](../../architecture/codebase-review-2026-10-21.md) (from `Mesiri_Codebase_Review.pdf`)
- [V1 tracker](../../plans/V1_TRACKER.md)
