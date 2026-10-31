> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged.

# Latency Optimization Roadmap

**Status:** Phase 0 pending deployment · **Baseline report:** 2026-07-26 (~180 messages, 7 days)
**Rule:** One phase per deployment. After each: deploy → 24h of traffic → run the latency report → compare against budget → freeze numbers → next phase. Never batch phases; batched deployments make it impossible to attribute improvement.

## Performance budget

Every optimisation targets a budget line, not "faster." An overage is stated as
"ingress exceeds budget by Xs," never "it feels slow."

| Stage | Budget | Baseline (2026-07-26) |
| --- | ---: | ---: |
| Ingress (media download+upload) | <500 ms | ~10-16 s (untraced, images) |
| Vision (`analyze_image`) | <2 s | 7.57 s avg |
| Extraction (`extract`) | <1.5 s | 3.72 s avg |
| Speech (`speech_to_text_translate`) | <1.5 s | 3.32 s avg |
| Workflow stage | <300 ms | 269 ms avg (1.2 s max, image-correlated) |
| **Total text** | **<2 s** | 2.6 s |
| **Total voice** | **<3 s** | 8.4 s |
| **Total image** | **<6 s** | 23.1 s |
| **Perceived (any type, after Phase 5)** | **<1 s** | seconds of silence |

## Already shipped (commits ~3cfc4f9..01837e6, 2026-07-26)

- `thinking_budget=0` on `extract`/`translate`/`transcribe`/`generate_json`
  (`analyze_image` keeps thinking — it earns its cost on handwriting).
- Gemini `max_retries` 2→1 (worst case per call 45s→30s).
- Provider instances cached in the resolver (no per-call TLS handshake).
- Redis AI-routing config TTL 5min (was: cached forever — routing changes
  silently never applied).
- **Ingress instrumented** (= Phase 2A): success-path `journey_traces` row with
  `download_ms` / `upload_ms` split, file size, mime type.
- **Interactive classifier instrumented**: each `generate_json` call
  (segmenter / extractor) writes an `interactive_classify` trace row. Finding:
  this path is a hidden 1-2 sequential LLM-call chain, previously invisible.

## Phases

### 0. Deploy + measure (next action)
Deploy what's committed. 24h of traffic. Re-run the report queries. This
baseline includes the 2A ingress split, so 2B is decided from data, not guesses.

### 1. Remove translate() from the text path
`extract` reads the original language directly; schema instructs English field
values. `extract` must return `detected_language`, `semantic_type`, and fields,
so nothing downstream depends on translation existing.
- Pro: deletes a network call (deleting work beats speeding work up); removes
  the component with three documented silent-failure production bugs.
- Con: the post-translation whoami/greeting re-check in
  `understanding/pipeline.py` must be covered by extract's `whoami_question`
  classification instead — needs a test.
- Gain: text 2.6s → ~1.5s.

### 2B. Optimise ingress (direction chosen by Phase 0 data)
Stream Meta CDN download to memory (kill the sync disk write/read-back that
blocks the event loop); run R2 upload concurrently with the vision call
(vision needs bytes, not the object key).
- Con: upload failure after reply → expense referencing missing media; needs
  retry-or-flag. Ingress is shared ownership (Alan) — coordinate.
- Gain: image 23s → ~10-12s.

### 3. Merge vision→extract into one call + downscale images (~1024px)
Only after side-by-side eval on real receipts AND attendance sheets
(`scripts/eval_attendance_photos.py` is the harness). Attendance sheets are the
risk case; do not remove `extract()` on assumption.
- Gain: −3.7s per image (and per voice message if audio→extraction merged too).

### 5. Ack-then-result UX (deliberately ahead of Phase 4)
Reply <500ms ("Got it — reading it now"), send the real result as a second
message. Perception beats total time: an instant ack + 5s result feels faster
than 5s of silence. The only change that makes the worst provider day feel
fine. Interactive taps get no ack (already fast).
- Con: two-message flow; workflow state must tolerate a user reply arriving
  between ack and result. Largest single item (2-4 days).

### 4. Async client + flash-lite for light calls (tail latency)
`client.aio.models` (removes the to_thread pool bottleneck behind p99≫p50);
route classifier/transcription to `gemini-2.5-flash-lite` via the resolver.
Deliberately after 5: don't chase p99 before average latency and perception are
fixed.

### 6. Evaluate alternative inference providers — experiment, not roadmap
Groq/Cerebras-class hosts for extraction (300-600ms) ONLY if Phases 1-5 miss
the budget. New provider = prompt differences, rate limits, outages, eval
effort. Not committed.

## Expected end-state

| path | today | after 1-3 | perceived after 5 |
| --- | ---: | ---: | ---: |
| text | 2.6s | ~1.5s | <1s |
| voice | 8.4s | ~2-3s | <1s |
| image | 23.1s | ~4-6s | <1s |
| interactive | 4.5s | ~1-2s | already fast |

Hard floors no phase removes: WhatsApp webhook+send round trip (~0.5-1.5s,
Meta-side) and any third-party model's p99. Phase 5 exists because of these.
