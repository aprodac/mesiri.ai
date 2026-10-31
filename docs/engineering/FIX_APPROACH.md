# How we fix things: the class, not the instance

> Set by Ilan, 29 Oct 2026: *"Whenever you see a bug or something, not a patch up. If there is a
> mistake, look for similar kinds of loopholes, similar situations, UX issues, everything. That's
> not how we want our smart architecture to be."*
>
> Applies to every fix in this repository: by a person, a Claude Code session, the team bot's
> approved plans, and the production watcher (TM-16). The root `CLAUDE.md` still governs process
> (phases, verification, git, approvals); this file governs **how a problem is understood and fixed**.

## The rule

A bug report is a sample of a class of failures. Fix the class at its root, in the one place that
owns it, and prove the neighbours are covered. A fix that only makes the reported message work is not done.

## Before writing code: four questions

1. **What is the mechanism?** Not "the bot said X", but *which decision* went wrong and *who made it*
   (the model, a rule in code, the data, a missing piece of context, a UX dead end). Reproduce it with the
   real path (replay test or golden case), and show the failure before fixing it.
2. **Where else does the same mechanism act?** List the siblings: other tools, other record kinds
   (labour / work / material / issue / expense / money), other entry points (typed, voice, photo, tap,
   swipe-reply, a follow-up), other languages, other states (open card, saved card, no card, several
   sites, several projects). Check each one. Most bugs this project has had came in families:
   - *the model was told what to call instead of the code calling it* -> four separate blocks, now one
     pipeline (`runtime/agent/reroute.py`, ADR draft-per-message section 25);
   - *a tap carried less context than the message that produced it* -> the issue-close project loop;
     check every list / button tap;
   - *a check matched a literal string* ("To save:") and missed every variant;
   - *a picture or a second model call put time on the reply path*.
3. **Where does the fix belong?** Prefer, in this order: the one shared place that owns the decision
   (a pipeline, a rule table, a resolver) -> extending it -> something new. Never a special case in a
   caller. If two places make the same decision, merge them first. A new case of a known kind should be
   one entry in an existing table, not new code.
4. **What does the user experience end to end?** Read the whole conversation as the site supervisor sees
   it: the words, the card, the buttons, what happens on the next message. Fix the wording, cues and dead
   ends found on the way (things that say "check the card" with no card, a question asked twice, an
   apology instead of an action, a reply that waits on something the user doesn't need yet).

## Where a fix belongs in v2

The assistant is [v2](../architecture/assistant-v2.md): one agent + skills + tools. Put a fix in the first of these that can own it: (1) a **rule in `SKILL.md`** (plain English; the model reads it); if the model cannot be trusted to follow it, (2) **a decision the code must enforce** in the runner or the tool (a check, a guard, a code-drawn line); if neither can express it, (3) **a new tool** that reuses the existing write path. Never a new workflow, router or word list. **Every fix adds an `evals.yaml` case** (the reported message, a sibling, and the guard that must not change).

## Non-negotiables

- **Time to reply is the top product constraint.** Nothing new goes on the reply path unless it pays for
  itself: draw, translate, upload and second model calls happen in parallel or after the reply.
- **The model reads; the code decides and acts.** When the code can tell the right action from the words
  and the state, the code takes it in the same turn. "Tell the model to call X" is the last resort.
- **One pipeline per decision.** Same kind of thing -> same path (saves, cards, reroutes, wording,
  site resolution). A second path for the same decision is a bug waiting to happen.
- **Honest replies.** Never claim something was saved, seen or changed unless the code did it; never
  ask the user to do what they just did.
- **Every fix leaves a test for the class**, not only the instance: the reported message, plus at least
  one sibling, plus the guard (the case that must *not* change, e.g. "alla, 6 mason aanu" is a
  correction, never more masons).

## The write-up (in the commit and the phase report)

- **Root cause:** the mechanism, in one or two lines.
- **Class:** the siblings checked, and which were also broken.
- **Fix:** where it lives and why there.
- **Guards:** what must not change, and the test that holds it.
- **Not covered:** what was not checked or could not run. A gap is said, never hidden.
