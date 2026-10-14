# Replay suite — real failures kept as regression cases (WA-15)

Each `cases/<id>.json` is one message a real user sent, what the AI understood, and what the
assistant should have done. `test_replay_cases.py` runs it through the real pipeline after the AI
step (context, canonicalization, gates, planner, workflow, reply), with the AI replaced by the
recorded understanding. That makes a case deterministic, offline, and fast.

Run: `pytest apps/whatsapp-assistant/tests/replay` (same PYTHONPATH as the rest of the suite).
Workflow cases need the `workflow` extra (LangGraph); without it they are **skipped**, and CI
does not install it today. See the WA-15 tracker note.

## Case format

```json
{
  "id": "same-as-file-name",
  "status": "passing | known_failure",
  "finding": "fingerprint in assistant_review_findings (required for known_failure)",
  "source": "where it came from: 'review 2026-10-15, u_ab12 @ 09:12' or 'example'",
  "description": "one sentence: what should happen",
  "sender": "engineer | director | abc_director | unknown",
  "message": {"text": "what they wrote (paraphrased, no names/numbers)", "modality": "text | voice"},
  "understanding": {
    "semantic_type": "material_update | expense | greeting | ...",
    "fields": {"material_name": "cement", "quantity": 50, "direction": "received"},
    "field_confidences": {"material_name": 0.95},
    "detected_language": "Malayalam", "transcript": "...", "translated_text": "..."
  },
  "expect": {
    "event_type": "MaterialReceiptRequested",
    "decision": "start_workflow | clarify | direct_reply | ...",
    "workflow_key": "material.receipt",
    "reply_kind": "text | list | buttons",
    "reply_contains": ["cement"],
    "reply_not_contains": ["material_name"],
    "reply_max_chars": 300,
    "options_include": ["Yes", "No"]
  }
}
```

Only include the `expect` keys the case is about. Text matching ignores case.

## Turning a real failure into a case

1. Find the conversation in the nightly export and the finding it belongs to.
2. Paraphrase the message onto the seed company (`src/context/seed.py`): its people, projects
   and sites. **Never** copy names, phone numbers or company details from the real one.
3. Take `understanding` from what the AI actually produced (the control panel's message
   "AI Context" shows it). If the AI itself misread the message, the case can't reproduce that
   offline: record the *correct* understanding and the expected outcome, and note in the
   finding that the fix is in the prompt.
4. Write `expect` as what *should* happen. Run it:
   - fails → `"status": "known_failure"` with `"finding"`. CI stays green; the case documents
     the bug.
   - passes → the bug isn't after the AI step (or it isn't reproducible in one message).
     Say so in the finding instead of adding a case that proves nothing.
5. When the fix lands, the case starts passing, and strict xfail turns CI red until you set
   `"status": "passing"` and mark the finding `fixed` with the commit.

## Limits

- One message per case. Follow-ups that depend on the previous turn (answering "which unit?",
  tapping Yes/No, a voice note after a photo) go through `runtime/message_journey.py`, which this
  harness does not drive yet (tracker WA-15b).
- Real company data (catalogs, people, stock) is replaced by the seed company, so problems that
  depend on a specific customer's data need a seed equivalent.
