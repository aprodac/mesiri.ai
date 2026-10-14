# Nightly assistant review — runbook (WA-14, WA-15)

> This is the instruction set the scheduled Claude Code session follows every night. Change the
> process by editing this file; the scheduled prompt only says "follow
> `docs/ops/assistant-review.md`". Plan: [self-improving-assistant-plan.md](../plans/self-improving-assistant-plan.md).

**The reviewer never changes product code.** It may write exactly two kinds of file:
- the report, `docs/reviews/YYYY-MM-DD.md`;
- replay cases, `apps/whatsapp-assistant/tests/replay/cases/*.json`, which are tests only.

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
2. Set up Python if needed:
   `uv venv --python 3.11 && uv pip install -e ".[dev,infra,providers,reports,workflow]"`
   (`workflow` = LangGraph, needed by the replay cases). Then fetch the last 24 h **into the
   scratchpad, never into the repo**:
   ```bash
   .venv/bin/python apps/whatsapp-assistant/scripts/fetch_review_export.py "$SCRATCH/export.json" --hours 24
   .venv/bin/python apps/whatsapp-assistant/scripts/review_findings.py list --status open > "$SCRATCH/open.json"
   .venv/bin/python apps/whatsapp-assistant/scripts/review_findings.py friction --days 14 > "$SCRATCH/trend.json"
   ```
   If this fails (missing secrets, 401, network), write a report saying exactly that, push it,
   and stop.
3. **Read in friction order.** Every conversation carries `friction.score` and
   `friction.signals`: repeat, negative, weak_negative, correction, abandoned, unsupported,
   failed, slow (computed by `apps/whatsapp-assistant/src/admin/friction.py`).
   - Read **every** conversation with a score ≥ 2, highest first, plus a random sample of at
     least 30 with no signals. Signals are hints, not verdicts: a "no" can be a fine answer.
   - Note signals that were wrong in **Rubric notes**, so the weights can be tuned.
   - For each conversation read, score the rubric axes and classify each problem
     ([rubric](../product/assistant-review-rubric.md)).
   - `understanding` on each message is what the AI made of it. Compare it with the text to
     tell `understanding` problems (the AI misread) from `routing`/`flow`/`copy` problems (the
     AI read it right and the code did the wrong thing).
4. Before calling something a bug, look at the code (`apps/whatsapp-assistant/src/...`) to
   understand *why* it happened. A finding names the likely file or function.
5. **Record findings.** One finding per *problem*, not per conversation. Give it a stable
   `fingerprint` (lowercase-with-dashes).
   - **Reuse the fingerprint from `open.json`** when it's the same problem: that's how it
     becomes recurring (`days_seen`). If you mint a new fingerprint for an old problem, the
     history is lost.
   - Write `$SCRATCH/findings.json` (format in `scripts/review_findings.py`), then run
     `review_findings.py record $SCRATCH/findings.json`. A problem previously marked `fixed`
     that you record again is reopened automatically: that's a regression, so say so in the
     report.
6. **Replay cases for recurring problems.** For each finding seen on 2+ days, or with severity
   3, that has no case yet:
   - Write one replay case per [tests/replay/README.md](../../apps/whatsapp-assistant/tests/replay/README.md),
     paraphrased onto the seed company, with `"status": "known_failure"` and `"finding"`.
   - Run `pytest apps/whatsapp-assistant/tests/replay` (same PYTHONPATH as the suite). Keep
     the case only if it is reported **xfailed**. If it passes, the bug isn't reproducible in
     one message after the AI step: drop the case and say so in the finding's `note`.
   - Link it: `review_findings.py update <fingerprint> --replay-case <case-id>`.
   - Nothing else in the repo may change. Before pushing, run the replay suite once more, and
     `ruff check` if you touched any Python (you shouldn't have).
7. **Trend.** From `trend.json`: friction rate per day and per workflow over 14 days. Say which
   workflows got better or worse. Note any finding marked `fixed` in the last days whose
   workflow's friction didn't drop.
8. Write `docs/reviews/YYYY-MM-DD.md` (template below). Commit report and cases together:
   `docs(reviews): assistant review YYYY-MM-DD`. Then pull, re-run the replay suite if the pull
   brought changes, and push to `main`.
9. If there were failures (`status` failed), a stage's p95 more than doubled against the last
   report, the friction rate rose by more than 10 points day over day, or a fixed finding was
   reopened, put **ALERT** in the first line of the report.

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
friction rate (today vs 7-day average) · top signals · share of conversations scoring ≤ 2 overall

## Top problems (most impact first)
| # | Fingerprint | Class | What happens | Times today | Days seen | Example | Likely cause (file) | Suggested fix | Replay case |

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
