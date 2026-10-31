> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# 04 SCENARIO REGISTRY

**Generated:** 2026-07-05T18:22:33.595715Z

## 1. Purpose
This document is the authoritative registry of executable product, architecture, integration, failure, recovery, security, AI-evaluation, cross-surface, and end-to-end scenarios for the whole Mesiri.ai system.

## 2. System Surfaces and Scenario Scope
1. **MOBILE** (React Native UI -> API -> Backend -> Domain -> Persistence)
2. **WHATSAPP** (User -> Ingress -> Understanding -> Canonical Event -> Planner -> Workflow Runtime -> Domain -> Persistence -> Outbound)
3. **BACKGROUND PROCESSING** (Scheduler/Worker -> Capabilities -> Persistence/Events/Read Models)

## 3. Core Principle
> A feature is not proven because its screen, route, module, workflow, or domain service exists.
> A scenario is proven only when a defined input travels through the required architecture boundaries, produces the expected observable result, preserves required invariants, and leaves inspectable evidence.

## 4. Scenario Classification
- UNIT_BEHAVIOR
- CONTRACT
- SURFACE_INTEGRATION
- MODULE_INTEGRATION
- CROSS_MODULE_INTEGRATION
- CROSS_SURFACE_PARITY
- FAILURE_INJECTION
- SECURITY
- IDEMPOTENCY
- RECOVERY
- CONCURRENCY
- AI_EVALUATION
- END_TO_END
- VERTICAL_SLICE
- PRODUCTION_SMOKE

## 5. Scenario Lifecycle
- DRAFT, READY, IMPLEMENTED, AUTOMATED, PASSING, FAILING, BLOCKED, FLAKY, DEPRECATED, RETIRED

## 6. Automation Levels
- L0 — DOCUMENTED ONLY
- L1 — MANUAL REPRODUCTION
- L2 — AUTOMATED MODULE TEST
- L3 — AUTOMATED CROSS-MODULE / SURFACE-INTEGRATION TEST
- L4 — AUTOMATED END-TO-END TEST
- L5 — PRODUCTION SMOKE / CONTINUOUS VERIFICATION

## 7. Priority Levels
- P0 — Release blocker, security, data integrity, or critical vertical slice.
- P1 — Required for milestone/release confidence.
- P2 — Important resilience or secondary behavior.
- P3 — Future coverage.

## 8. Scenario Registry Rules
- Every scenario entry must track all required fields.
- Do not guess unknown values (use TBD, NOT_FOUND, NOT_AUTOMATED, etc).

## 9. Master Scenario Table

| ID | Scenario | Initiating Surface | Type | Priority | Owner | Modules/Layers | API/Contracts | Automation Level | Current Result | Gate | Evidence |
|----|----------|-------------------|------|----------|-------|----------------|---------------|------------------|----------------|------|----------|
| SCN-004 | Duplicate Webhook | WhatsApp | IDEMPOTENCY | P0 | TBD | Ingress, Understanding | Webhook API | L0 | NOT_AUTOMATED | V0.1 | NO_CURRENT_EVIDENCE |
| SCN-009 | Model Timeout and Fallback | WhatsApp | RECOVERY | P0 | TBD | Platform AI | AI Provider | L0 | NOT_AUTOMATED | V0.1 | NO_CURRENT_EVIDENCE |

## 10. Mobile Feature Coverage Matrix

| Route / Feature | Screen | Current UI State | Data Source | API Endpoint | Backend Handler | Application Use Case | Domain Operation | Persistence Effect | Events | Tests | Scenario IDs | Current Evidence | Status |
|-----------------|--------|------------------|-------------|--------------|-----------------|----------------------|------------------|--------------------|--------|-------|--------------|------------------|--------|
| login | login.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | LOCAL_STATE_ONLY |
| _layout | _layout.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | LOCAL_STATE_ONLY |
| (app)/analytics | (app)\analytics.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/field | (app)\field.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/index | (app)\index.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/profile | (app)\profile.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | LOCAL_STATE_ONLY |
| (app)/reports | (app)\reports.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/sites | (app)\sites.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/timeline | (app)\timeline.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/users | (app)\users.tsx | TBD | TBD | Unknown API | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | API_WIRED |
| (app)/_layout | (app)\_layout.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | MOCK_DATA |
| (app)/projects/index | (app)\projects\index.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/projects/new | (app)\projects\new.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| (app)/settings/theme | (app)\settings\theme.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | UI_ONLY |
| profile | profile.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| users | users.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| sites | sites.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| reports | reports.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| analytics | analytics.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| field | field.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| timeline | timeline.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| projects/index | projects/index.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| projects/new | projects/new.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |
| settings/theme | settings/theme.tsx | TBD | TBD | None | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | NOT_FOUND | None | NOT_FOUND | NO_CURRENT_EVIDENCE | NOT_FOUND |

## 11. Surface → Backend → Domain Traceability Matrix
*(Traceability not proven for most routes yet as implementation is missing or stubbed)*

| Surface | User Action | Transport | Endpoint / Entry Point | Application Use Case | Domain Operation | Repository Port | Infrastructure Adapter | Database Tables | Domain Events | Consumers | Read Models / Timeline Effects | Notifications | Scenario IDs | Tests | Evidence |
|---------|-------------|-----------|------------------------|----------------------|------------------|-----------------|------------------------|-----------------|---------------|-----------|--------------------------------|---------------|--------------|-------|----------|
| Mobile | Create Project | HTTP | POST /projects | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | SCN-010 | NONE | NO_CURRENT_EVIDENCE |
| WhatsApp | Report Equipment | Webhook | POST /webhook | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | SCN-011 | NONE | NO_CURRENT_EVIDENCE |

## 12. Cross-Surface Parity Registry
| Capability | Mobile Path | WhatsApp Path | Shared Application Use Case | Shared Domain Operation | Current Status |
|------------|-------------|---------------|-----------------------------|-------------------------|----------------|
| Project Creation | POST /projects | Planner -> Project Workflow | TBD | TBD | BLOCKED / NOT_IMPLEMENTED |

## 13. Detailed Existing Scenario Entries

### SCN-004 Duplicate Webhook
- **scenario_id**: SCN-004
- **name**: Duplicate Webhook Safety
- **scenario_type**: IDEMPOTENCY
- **initiating_surface**: WHATSAPP
- **status**: DRAFT
- **automation_level**: L0
- **priority**: P0
- **last_result**: NO_CURRENT_EVIDENCE

### SCN-009 Model Timeout and Fallback
- **scenario_id**: SCN-009
- **name**: Model Timeout and Fallback
- **scenario_type**: RECOVERY
- **initiating_surface**: WHATSAPP
- **status**: DRAFT
- **automation_level**: L0
- **priority**: P0
- **last_result**: NO_CURRENT_EVIDENCE

## 14. Critical WhatsApp Vertical Slices
- **SCN-011: Critical WhatsApp Vertical Slice A — WhatsApp JCB Usage** (Missing automation)
- **SCN-012: Critical WhatsApp Vertical Slice B — WhatsApp Receipt Expense** (Missing automation)

## 15. Critical Mobile Vertical Slices
- **SCN-010: Critical Mobile Vertical Slice C — Mobile Project Creation** (Missing automation)
- **SCN-013: Critical Mobile Vertical Slice D — Mobile Scope Isolation** (Missing automation)

## 16. Cross-Surface Vertical Slices
- **SCN-014: Critical Vertical Slice E — Cross-Surface Business Parity** (Blocked, none exist)

## 17. Shared Invariant Registry
- **INV-001 Tenant Isolation**: TBD
- **INV-002 Duplicate Webhook Safety**: TBD
- **INV-003 Duplicate Business Action Safety**: TBD
- **INV-004 Correlation Propagation**: TBD
- **INV-005 Contract Validity**: TBD
- **INV-006 Domain Write Boundary**: TBD
- **INV-007 Provider Isolation**: TBD
- **INV-008 Transport Isolation**: TBD
- **INV-009 Atomic Domain Event Persistence**: TBD
- **INV-010 Consumer Idempotency**: TBD
- **INV-011 Workflow Recoverability**: TBD
- **INV-012 Authorization Before Action**: TBD
- **INV-013 AI Cannot Bypass Deterministic Controls**: TBD
- **INV-014 Evidence Requirement**: TBD
- **INV-015 Shared Business Truth Across Surfaces**: TBD
- **INV-016 Backend Authorization Is Authoritative**: TBD
- **INV-017 Mobile Retry Safety**: TBD
- **INV-018 Scope Cache Isolation**: TBD
- **INV-019 Surface Independence**: TBD

## 18. Milestone and Release Gate Coverage Matrix
V0.1 is BLOCKED until P0 scenarios are proven. Current passing P0 count: 0.

## 19. Scenario Execution Suites
- PR_FAST: (Empty)
- MOBILE_PR_FAST: (Empty)
- BACKEND_PR_FAST: (Empty)
- ASSISTANT_PR_FAST: (Empty)
- VERTICAL_SLICE_GATE: SCN-010, SCN-011, SCN-012, SCN-013, SCN-014 (All Failing/Missing)

## 20. Evidence Requirements
Evidence requires OpenTelemetry trace, Database query result, test output, outbox record, timeline model update. "Developer observed it working" is not sufficient.

## 21. Failure Injection Coverage
Missing scenarios for: Redis unavailable, Database failure, outbox crash.

## 22. Recovery Coverage
SCN-009 defined but missing execution. SCN-015 (Workflow Restart Recovery) missing.

## 23. Concurrency Coverage
Missing scenarios.

## 24. Security Coverage
Missing scenarios for role authorization.

## 25. AI Evaluation Coverage
Missing evaluation datasets for understanding provider.

## 26. Missing Scenario Coverage
- **SCN-010**: Mobile Project Creation (P0)
- **SCN-011**: WhatsApp JCB Usage (P0)
- **SCN-012**: WhatsApp Receipt Expense (P0)
- **SCN-013**: Mobile Scope Isolation (P0)
- **SCN-014**: Cross-Surface Business Parity (P0)
- **SCN-015**: Workflow Restart Recovery (P0)

## 27. Architecture and Execution Drift Detected
- No E2E execution paths could be successfully traced from surface to domain events. Mobile routes exist but are mostly UI-only or not wired to full backend pipelines.

## 28. Scenario Creation Process
TBD

## 29. Scenario Change Process
TBD

## 30. Scenario Deprecation Process
TBD

## 31. CI Integration Recommendations
Ensure gates block on scenario evidence, not just unit test passes.

## 32. Current Highest-Risk Gaps
1. Total lack of E2E automated test evidence
2. Mobile UI not connected to backend domain
3. No idempotency controls proven
4. WhatsApp workflows stubbed/mocked
5. Lack of traceability from webhook to timeline

## 33. Immediate Actions — Ilan
- Build E2E testing framework for WhatsApp ingestion

## 34. Immediate Actions — Alan
- Wire Mobile Project Creation API to Backend

## 35. Immediate Shared Actions
- Implement the Missing Scenario Coverage

## 36. Approval Checklist
- [ ] V0.1 gating criteria approved

## 37. Final Rule
A scenario is proven only when a defined input travels through the required architecture boundaries, produces the expected observable result, preserves required invariants, and leaves inspectable evidence.
