# Assistant review rubric

> Used by the nightly reviewer (WA-14, [runbook](../ops/assistant-review.md)) to judge every
> WhatsApp conversation. Tune it when the reviewer's picks disagree with a human's — that is
> the main job of the first two weeks.

The user is a construction worker or site engineer on a phone, often outdoors, often typing in
Hinglish, Malayalam, Tamil or Hindi, often sending voice notes and photos. **The best reply is
the one that creates the least work for them.**

## Score each conversation 1–5 on each axis

| Axis | 5 = | 1 = |
| --- | --- | --- |
| **Understood** | Got what they meant first time, including slang, mixed language, units ("bags", "nos", "sqft") | Misread the request, or asked them to restate something it already had |
| **Right action** | Started the right workflow with the right project/site/material/people | Wrong workflow, wrong entity, or nothing happened |
| **Reply quality** | Short (fits one phone screen), in the sender's language, plain words, one clear next step | Long, English to a non-English sender, jargon, several questions at once |
| **Effort** | Fewest possible messages; nothing asked that the system already knew or could infer | Asked for things it had (project, date, unit), or made them repeat themselves |
| **Speed** | Text reply in < 5 s, voice/photo in < 15 s (`wall_ms`) | > 20 s, or a stage that is far above its usual p95 in `stage_summary` |

**Overall** = the lowest axis, not the average: one bad axis ruins the conversation for the user.

## Friction signals to look for

These are signs that something went wrong, even when the system recorded success:

- The user sends the same thing again, or rephrases it, within a couple of minutes.
- "no", "wrong", "galat", "nahi", "cancel", "undo", "not this" after a reply or confirmation.
- A correction or reverse workflow right after a capture.
- A workflow that stops partway (`workflow_phase` not completed) and the user moves on.
- The "I can't do that yet" / capability-help reply. This is **unmet demand**: record what they
  wanted.
- `status` failed, or any stage with `ok: false`.
- Many AI calls for one simple message, or one slow provider call dominating `wall_ms`.

## Classify every problem

| Class | Meaning | Typical fix (WA-16/17) |
| --- | --- | --- |
| `copy` | Reply wording, length, language | Reply template / prompt text |
| `understanding` | Misread text, voice, photo | Prompt, examples, classifier |
| `routing` | Wrong workflow or entity | Planner examples, entity resolution |
| `flow` | Too many turns, asked for known info | Workflow logic |
| `speed` | Slow stage or provider | Latency fix |
| `error` | Failure, exception, nothing sent | Bug fix |
| `unmet` | They wanted something the assistant can't do | New workflow (WA-17) |

Out of bounds for automatic fixes, so report only: Labour, Attendance, Payroll, Workforce, money
calculations, auth/tenancy.
