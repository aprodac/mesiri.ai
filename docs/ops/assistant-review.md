# Nightly assistant review — runbook (WA-14)

> This is the instruction set the scheduled Claude Code session follows every night. Change the
> process by editing this file; the scheduled prompt only says "follow
> `docs/ops/assistant-review.md`". Plan: [self-improving-assistant-plan.md](../plans/self-improving-assistant-plan.md).

**Stage 1 is read-only.** The reviewer does not change product code. It produces a report.
Fixing comes in WA-16/WA-17, and only after approval.

## Setup (once)

1. A **platform-admin** login for the reviewer (role ADMIN, no organization). Use a dedicated
   account, not a person's, so it can be revoked on its own.
2. Add these as **environment secrets** in the Claude Code environment the Routine runs in:
   - `MESIRI_REVIEW_EMAIL`, `MESIRI_REVIEW_PASSWORD` (or `MESIRI_REVIEW_TOKEN`, a JWT that
     lasts 7 days)
   - optional `MESIRI_REVIEW_API` (default `https://api.whatsapp.mesiri.ai`)
3. Optional, on the VPS `.env`: `MESIRI_REVIEW_HASH_KEY`, a long random string. User and
   company pseudonyms are keyed with it (it falls back to the JWT secret). Changing it changes
   every pseudonym, so set it once.

## Each night

1. `git checkout main && git pull origin main`.
2. Set up Python if needed (`uv venv --python 3.11 && uv pip install -e ".[dev,infra,providers,reports]"`),
   then fetch the last 24 h **into the scratchpad, never into the repo**:
   ```bash
   .venv/bin/python apps/whatsapp-assistant/scripts/fetch_review_export.py "$SCRATCH/export.json" --hours 24
   ```
   If this fails (missing secrets, 401, network), write a report saying exactly that, push it,
   and stop.
3. Read [the rubric](../product/assistant-review-rubric.md). Then go through **every**
   conversation in the export:
   - Score each axis 1–5 and the overall.
   - Note the friction signals.
   - Classify each problem.
   On a busy day, read every conversation that has a friction signal, a failure, or
   `wall_ms` > 15 s, plus a random sample of at least 30 of the rest.
4. Before calling something a bug, look at the code (`apps/whatsapp-assistant/src/...`) to
   understand *why* it happened. A finding names the likely file or function.
5. Compare with the previous reports in `docs/reviews/`. A problem seen again is a **recurring**
   one; say how many days it has appeared.
6. Write `docs/reviews/YYYY-MM-DD.md` (template below), commit
   `docs(reviews): assistant review YYYY-MM-DD`, then pull and push to `main`. Docs only.
7. If there were failures (`status` failed) or a stage's p95 more than doubled against the
   last report, put **ALERT** in the first line of the report.

## Privacy rules (non-negotiable)

- Never commit the export JSON or paste it anywhere.
- Quote users only in short fragments (≤ 12 words) when the exact words matter, e.g. a
  misunderstood phrase. Otherwise paraphrase.
- If a fragment contains a person's name, replace it with `[name]`.
- Refer to conversations as `u_xxxx @ HH:MM`, which an admin can match in the control
  panel's logs by time.

## Report template

```markdown
# Assistant review — YYYY-MM-DD

(ALERT line if any)

## Numbers
messages · conversations · users · companies · failed · median/p95 wall time by type ·
share of conversations scoring ≤ 2 overall

## Top problems (most impact first)
| # | Class | What happens | Times today | Days seen | Example | Likely cause (file) | Suggested fix |

## Unmet demand (things people asked for that we can't do)
| Request (paraphrased) | Times | Users | Companies | Days seen |

## Speed
Stages/providers whose p95 rose; worst 5 messages with where the time went.

## Worst 5 conversations
One short paragraph each: what the user wanted, what happened, what ideal would look like.

## What went well
2–3 lines. Patterns that work and must not regress.

## Rubric notes
Cases the rubric handled badly; a suggested rubric change, if any.
```
