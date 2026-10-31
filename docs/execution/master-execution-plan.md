> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Mesiri.ai — Master Execution Plan

**Status:** ACTIVE  
**Release Target:** Assistant Runtime V0.1  
**Maintainer:** Ilan  
**Approvers:** Ilan + Alan  
**Last Updated:** 2026-07-04

## Purpose
Single operational source of truth for milestone order, parallel work, ownership, dependencies, contracts, progress, blockers, metrics, gates, and evidence.

## Execution Principle
> Do not move forward because the code looks complete. Move forward because a real scenario passes.

A milestone passes only when decisions and contracts are approved, weighted deliverables are complete, required tests/scenarios pass, metrics meet thresholds, the visible demo succeeds, evidence is attached, and owner/reviewer approve.

## Release Target
`WhatsApp → Ingress → NormalizedMessage → Understanding → Context → CanonicalEvent → Planner → Workflow → Memory → Rules → Tools → Interaction → Confirmation/Approval → Domain Service → PostgreSQL + Outbox → Consumers → Timeline/Notification → WhatsApp Receipt`

## Current Milestones
| Milestone | Name | Owner | Status |
|---|---|---|---|
| M0 | Architecture Contract Gate | Both | ACTIVE until executable gate passes |
| M1 | Infrastructure Alive | TBD | ACTIVE / verify state |
| M2 | Real WhatsApp Ingress | Alan | ACTIVE |
| M3 | Understanding Pipeline | Ilan | ACTIVE |
| M4–M14 | V0.1 remaining gates | TBD | LOCKED |
| M15–M16 | Expansion + Semantic Memory | TBD | POST-V0.1 |

Statuses: `LOCKED`, `READY`, `ACTIVE`, `BLOCKED`, `GATE_REVIEW`, `PASSED`, `FAILED`, `DEFERRED`.

## Progress Rules
Progress is calculated from weighted deliverables, never subjective estimates. A deliverable contributes its full weight only when DONE. The final gate weight is awarded only after owner/reviewer approval.

## Current Parallel Work
- Alan owns M2 and produces `NormalizedMessage.v1`.
- Ilan owns M3 and consumes approved `NormalizedMessage.v1` fixtures.
- Ilan produces `UnderstandingResult.v1`.
- M3 must not depend on unfinished M2 implementation details.
- M2 must not perform semantic understanding.
- M3 must not parse raw WhatsApp payloads.
- Frozen contracts require both producer and consumer approval to change.
- Integration must require no permanent field-renaming glue code.

## INT-001 — M2 + M3 Integration Gate
Primary proof:

`Real WhatsApp Malayalam Voice → M2 → schema-valid NormalizedMessage.v1 → M3 → transcript → English normalization → structured extraction → schema-valid UnderstandingResult.v1`

Expected facts: `equipment_name = JCB`, `duration_hours = 4`.

Secondary proof:

`Real WhatsApp Receipt Image → M2 → NormalizedMessage.v1 → M3 → vision/OCR → structured expense fields`

Required properties:
- same `correlation_id` across M2/M3;
- schema-valid outputs;
- no duplicate downstream processing;
- no permanent transformation glue;
- provider failures observable;
- latency recorded;
- integration trace inspectable.

## Ownership
### Alan — M2
Owns webhook verification, raw payload parsing, deduplication, media ingestion, normalization, M2 tests/demo, and `NormalizedMessage.v1` production. Reviews M3 shared boundaries and gate evidence.

### Ilan — M3
Owns content routing, STT/translation/vision coordination, structured extraction, confidence/ambiguity handling, provider fallback behavior, M3 tests/evals/demo, and `UnderstandingResult.v1` production. Reviews M2 shared boundaries and gate evidence.

## M2 Weighted Deliverables
| Deliverable | Weight |
|---|---:|
| NormalizedMessage contract approved | 10% |
| Webhook verification | 5% |
| Text normalization | 10% |
| Image normalization | 10% |
| Voice normalization | 10% |
| Interactive-message normalization | 10% |
| Reply-context normalization | 5% |
| Media ingestion | 10% |
| Sequential deduplication | 5% |
| Concurrent deduplication | 5% |
| Structured error handling | 5% |
| Contract tests passing | 5% |
| Real WhatsApp demo passed | 5% |
| Gate approved | 5% |

## M3 Weighted Deliverables
| Deliverable | Weight |
|---|---:|
| UnderstandingResult contract approved | 10% |
| Provider interfaces implemented | 10% |
| Content router | 5% |
| Text path | 10% |
| Voice path | 15% |
| Image path | 15% |
| Structured extraction | 10% |
| Confidence/ambiguity handling | 5% |
| Fallback/error handling | 5% |
| Contract tests passing | 5% |
| Live evaluation passed | 5% |
| Gate approved | 5% |

## Success Metrics
### M2
| Metric | Target |
|---|---:|
| Webhook acknowledgement p95 | < 500 ms |
| Text normalization p95 | < 250 ms |
| Duplicate prevention | 100% |
| Schema-valid outputs | 100% |
| Correlation propagation | 100% |
| Required message-type coverage | 100% |
| Unhandled gate-suite exceptions | 0 |

### M3
| Metric | Target |
|---|---:|
| Schema-valid UnderstandingResult | 100% |
| Correlation propagation | 100% |
| Injected provider failures handled | 100% |
| Unhandled gate-suite exceptions | 0 |
| Receipt amount extraction accuracy | ≥ 98% |
| Equipment + duration extraction accuracy | ≥ 95% |
| Malayalam meaning preservation | ≥ 95% |
| Ambiguity detection recall | ≥ 90% |
| Text understanding p95 | < 3 s |
| Image understanding p95 | < 5 s |
| Voice understanding p95 | < 7 s |

AI quality targets must be measured on a versioned evaluation dataset and revised only from measured baselines.

## Decisions Required Before INT-001
- [ ] Approve `NormalizedMessage.v1`.
- [ ] Approve `UnderstandingResult.v1`.
- [ ] Commit shared M2→M3 fixtures.
- [ ] Approve media handoff mechanism.
- [ ] Approve correlation-ID behavior.
- [ ] Approve M3 provider interfaces.
- [ ] Create initial M3 live evaluation dataset.
- [ ] Approve latency measurement format.
- [ ] Approve structured error propagation.
- [ ] Approve integration branch strategy.

## Gate Review Process
1. Freeze milestone changes except gate fixes.
2. Run required unit, contract, integration, scenario, failure-injection, and live-evaluation tests.
3. Record metrics.
4. Run visible demo.
5. Attach evidence.
6. Reviewer independently verifies evidence.
7. Record PASS or FAIL.

No partial milestone pass exists.

## Contract Change Rule
`Problem → Contract Change Request → Identify producers/consumers → Record compatibility impact → Producer + consumer approval → Update schema/fixtures/tests → Update implementations → Pass integration tests → Update version/change history`

No developer may locally fork a shared contract.

## Integration Failure Rule
If producer output violates the contract, producer fixes it. If producer output matches the contract but consumer rejects it, consumer fixes it. If the contract is wrong, create a Contract Change Request. Do not add permanent glue code to hide incompatible implementations.

## Git Strategy
`feat/m2-*` and `feat/m3-*` merge by PR into `integration/m2-m3`, which merges by PR into `main`.

Rules:
- no direct pushes to `main` or active integration branches;
- CI green before merge;
- cross-boundary changes require the other developer's review;
- contract tests mandatory for producers and consumers;
- merged migrations are immutable;
- integration failures block the gate;
- gate report committed before marking a milestone passed.

## Evidence Locations
- `docs/execution/gates/`
- `docs/execution/evals/results/`
- CI artifacts for tests
- trace links/exports referenced by gate reports

## Daily Update
Each developer records: active milestone, completed deliverables, current deliverable, next deliverable, blockers, contract-change requests, affected scenarios, integration risk, and expected next gate date.

## Current Next Actions
### Alan
1. Review/approve `NormalizedMessage.v1`.
2. Create M2 shared fixtures.
3. Implement webhook verification.
4. Implement text normalization.
5. Implement deduplication baseline.
6. Add M2 contract tests.
7. Continue message types/media ingestion.

### Ilan
1. Review/approve `NormalizedMessage.v1`.
2. Define `UnderstandingResult.v1`.
3. Create M3 shared fixtures.
4. Define provider interfaces.
5. Implement content router.
6. Implement text path.
7. Create initial M3 evaluation dataset.

### Shared
1. Approve M2→M3 boundary.
2. Approve media handoff.
3. Approve correlation-ID behavior.
4. Approve structured error propagation.
5. Create `integration/m2-m3`.
6. Schedule first integration run.

## V0.1 Exit Condition
V0.1 passes only when a real WhatsApp user completes the receipt-expense vertical slice through understanding, context, workflow, memory, rules, confirmation/approval, domain persistence, outbox/events, timeline/notification, and receipt delivery.

Additionally:
- duplicate webhook delivery does not duplicate processing;
- duplicate confirmation does not duplicate business records;
- pending workflows survive server restart;
- consumer crashes do not lose domain events;
- provider failures follow fallback/error policy;
- requests are traceable end-to-end;
- required scenarios pass;
- required success metrics meet thresholds.
