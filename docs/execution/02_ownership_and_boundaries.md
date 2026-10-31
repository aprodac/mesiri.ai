# Mesiri.ai — Ownership and Boundaries

**Document:** `02_OWNERSHIP_AND_BOUNDARIES.md`  
**Status:** ACTIVE  
**Release Target:** Assistant Runtime V0.1  
**Maintainer:** Ilan  
**Approvers:** Ilan + Alan  
**Last Updated:** 2026-07-04

---

# 1. Purpose

This document defines ownership, responsibility, dependency direction, modification authority, review requirements, and architectural boundaries across the Mesiri.ai codebase.

The purpose is to allow multiple developers to work in parallel without:

- duplicating responsibilities,
- implementing incompatible components,
- bypassing contracts,
- introducing hidden dependencies,
- writing business logic in transport layers,
- accessing infrastructure directly from workflows,
- changing shared contracts independently,
- or creating services that cannot later be integrated.

This document answers:

> Who owns this code?

> What is this module responsible for?

> What may this module depend on?

> What is this module forbidden from doing?

> Who must approve changes?

> What happens when work crosses an ownership boundary?

---

# 2. Core Rule

> Ownership controls who implements code. Boundaries control what the code is allowed to do.

Ownership does not give permission to violate architecture boundaries.

The primary owner of a module may make implementation decisions inside that module as long as:

- frozen contracts are respected,
- dependency rules are respected,
- persistence boundaries are respected,
- infrastructure access rules are respected,
- public interfaces remain compatible,
- required tests continue passing,
- and architectural decisions are not silently changed.

Neither developer may bypass a boundary because doing so is faster.

---

# 3. Ownership Model

Every meaningful module has:

```text
PRIMARY OWNER

Responsible for implementation,
tests,
maintenance,
documentation,
and milestone delivery.


REQUIRED REVIEWER

Reviews changes affecting:
public interfaces,
shared contracts,
cross-module behavior,
architecture boundaries,
and integration behavior.


CONSUMERS

Modules depending on the output
or behavior of this module.


DEPENDENCIES

Modules and interfaces this module
is allowed to use.
```

There must be exactly one primary owner for active implementation work.

Shared ownership is allowed for architecture decisions.

Shared ownership should not be used for day-to-day implementation responsibility.

---

# 4. Ownership Authority Levels

## PRIMARY OWNER

May independently:

* implement internal code,
* refactor internal implementation,
* add internal tests,
* add private helpers,
* improve observability,
* fix bugs that do not change public behavior.

Requires review for:

* public interface changes,
* shared contract changes,
* new cross-module dependencies,
* persistence behavior changes,
* infrastructure access changes,
* security boundary changes,
* milestone gate changes.

---

## REQUIRED REVIEWER

Responsible for checking:

* contract compatibility,
* dependency direction,
* integration behavior,
* architecture boundary compliance,
* tests covering shared behavior,
* unexpected coupling.

The reviewer should not dictate internal implementation details unless those details affect shared architecture.

---

## SHARED ARCHITECTURE APPROVAL

The following require approval from both Ilan and Alan:

* frozen contract changes,
* repository boundary changes,
* new deployable services,
* database ownership changes,
* direct cross-service database access,
* event envelope changes,
* ID strategy changes,
* error contract changes,
* authentication architecture changes,
* authorization architecture changes,
* persistence boundary changes,
* workflow/domain responsibility changes,
* replacing major infrastructure technology,
* bypassing the Tool Executor,
* bypassing Domain Services,
* changing milestone exit conditions.

---

# 5. Current Developer Ownership

## Alan

Primary owner:

```text
M2 — Real WhatsApp Ingress

services/whatsapp/
```

Responsibilities:

* webhook verification,
* WhatsApp webhook handling,
* raw payload parsing,
* provider payload validation,
* message deduplication,
* media reference extraction,
* media ingestion coordination,
* WhatsApp message normalization,
* interactive response normalization,
* reply-context extraction,
* production of `NormalizedMessage.v1`,
* M2 unit tests,
* M2 contract tests,
* M2 integration tests,
* M2 failure tests,
* M2 visible demo,
* M2 gate evidence.

Alan is also the required reviewer for:

```text
M3 shared-boundary changes

UnderstandingResult.v1

M3 → future consumer compatibility

M3 integration evidence
```

---

## Ilan

Primary owner:

```text
M3 — Understanding Pipeline

services/assistant/**/understanding/
```

Responsibilities:

* content routing,
* text understanding path,
* speech-to-text coordination,
* translation coordination,
* image understanding coordination,
* OCR coordination when required,
* structured extraction,
* provider interfaces,
* provider routing,
* provider fallback behavior,
* output validation,
* confidence handling,
* ambiguity detection,
* production of `UnderstandingResult.v1`,
* M3 unit tests,
* M3 contract tests,
* M3 integration tests,
* M3 evaluation suite,
* M3 failure tests,
* M3 visible demo,
* M3 gate evidence.

Ilan is also the required reviewer for:

```text
M2 shared-boundary changes

NormalizedMessage.v1

M2 → M3 compatibility

M2 integration evidence
```

---

# 6. Repository Ownership Map

```text
Mesiri.AI/
│
├── apps/
│   ├── control-panel/              FUTURE OWNER ASSIGNMENT
│   ├── dashboard/                  FUTURE OWNER ASSIGNMENT
│   ├── desktop/                    FUTURE OWNER ASSIGNMENT
│   ├── marketing-site/             FUTURE OWNER ASSIGNMENT
│   └── mobile/                     FUTURE OWNER ASSIGNMENT
│
├── packages/
│   ├── api-client/                 SHARED BOUNDARY
│   ├── auth/                       SHARED ARCHITECTURE
│   ├── config/                     SHARED
│   ├── contracts/                  CONTRACT OWNERSHIP RULES APPLY
│   ├── database/                   DATABASE OWNERSHIP RULES APPLY
│   ├── logger/                     SHARED
│   ├── types/                      SHARED BOUNDARY
│   ├── ui/                         FRONTEND OWNERSHIP
│   └── utils/                      SHARED — RESTRICTED
│
├── services/
│   ├── api/                        FUTURE OWNER ASSIGNMENT
│   ├── whatsapp/                   ALAN — PRIMARY OWNER
│   ├── assistant/                  MILESTONE/MODULE OWNERSHIP
│   ├── domain/                     DOMAIN OWNERSHIP RULES APPLY
│   ├── platform/                   CAPABILITY OWNERSHIP RULES APPLY
│   ├── infrastructure/             ADAPTER OWNERSHIP RULES APPLY
│   ├── workers/                    FUTURE OWNER ASSIGNMENT
│   ├── scheduler/                  FUTURE OWNER ASSIGNMENT
│   ├── notification/               FUTURE OWNER ASSIGNMENT
│   ├── analytics/                  FUTURE OWNER ASSIGNMENT
│   └── ai-workers/                 FUTURE OWNER ASSIGNMENT
│
├── scenarios/                      SHARED PRODUCT BEHAVIOR
│
├── docs/execution/                 SHARED EXECUTION CONTROL
│
└── infrastructure/                 SHARED ARCHITECTURE
```

Ownership for future milestones must be assigned before the milestone becomes `ACTIVE`.

---

# 7. Directory Modification Rules

Directories are classified into four categories.

## OWNER-CONTROLLED

The primary owner may modify internal implementation without prior approval.

Examples:

```text
services/whatsapp/src/webhook/

services/whatsapp/src/normalization/

services/assistant/**/understanding/
```

Changes affecting public interfaces still require review.

---

## CROSS-REVIEW REQUIRED

Changes require review from the affected producer or consumer.

Examples:

```text
packages/contracts/

shared fixtures

public service interfaces

provider ports

domain ports

event schemas

API contracts
```

---

## SHARED ARCHITECTURE

Changes require approval from both developers.

Examples:

```text
repository structure

service boundaries

database ownership

dependency direction

persistence rules

ID strategy

error contract

event envelope

authorization model
```

---

## GENERATED

Generated code must not be manually edited.

Examples:

```text
packages/contracts/generated/

packages/api-client/generated/

packages/database/generated/
```

Changes must happen at the authoritative source and then regenerate artifacts.

---

# 8. Service Boundary Principles

Mesiri uses the following conceptual separation:

```text
TRANSPORTS

WhatsApp
HTTP API
Mobile
Dashboard
Workers
Scheduler

        ↓

APPLICATION / ASSISTANT ORCHESTRATION

        ↓

DOMAIN CORE

        ↓

PORTS / INTERFACES

        ↓

INFRASTRUCTURE ADAPTERS
```

Additionally:

```text
ASSISTANT ORCHESTRATION

        ↓

PLATFORM CAPABILITIES

Tools
Rules
AI Gateway
Authorization
Idempotency
Observability
Events
```

Dependency direction must move toward stable business abstractions.

Infrastructure technology must not become the architecture.

---

# 9. WhatsApp Service Boundary

## OWNS

```text
Webhook verification

Webhook acknowledgement

Raw WhatsApp payload parsing

Provider-specific validation

External message ID extraction

Message deduplication entry check

Media reference extraction

Interactive response parsing

Reply-context parsing

NormalizedMessage production

WhatsApp delivery adapter
```

## CONSUMES

```text
WhatsApp provider SDK/API

Idempotency interface

Object storage/media interface

NormalizedMessage contract

Structured error contract

ID utilities

Logging/tracing interfaces
```

## PRODUCES

```text
NormalizedMessage.v1

WhatsApp delivery status

Transport-level errors

Transport-level telemetry
```

## MUST NOT

```text
Perform semantic understanding

Call Gemini for reasoning

Call DeepSeek for planning

Call Sarvam for transcription

Select workflows

Resolve business context

Evaluate business rules

Execute domain commands

Create expenses

Create equipment records

Create material records

Directly modify workflow state

Implement business approval logic
```

---

# 10. Assistant Agent Boundary (agent_v2)

> Replaces the former "Understanding Module" section. The assistant is now **one agent + skills + tools**
> ([assistant-v2.md](../architecture/assistant-v2.md)). The classic understanding pipeline is retiring.
> Status: v2 is live on the 2 test companies only; real customers run classic.

## OWNS

```text
Reading every eligible message (text or voice) and deciding what it holds

Choosing which tools to call, and asking when something is unclear

Writing the reply in the sender's language

The context given to the model (sites, today's records, open card, last turns, catalog)

The switch side: eligibility, fallback to classic on a failure before any action, loop guard

Shadow runs and their report
```

Owner: `apps/whatsapp-assistant/src/agent_v2/` (`runner.py`, `agents/main.py`). Switch: `runtime/message_journey.py`.

## MUST NOT

```text
Write a record itself (only tools put lines on the draft card; only the Save tap writes)

Add a workflow, router, classifier or word list

Call a provider SDK directly (it goes through ToolCallingProvider in platform/ai)

Touch Labour, Attendance, Payroll or Workforce rules or data paths
```

---

# 11. Context Module Boundary

## OWNS

```text
Organization resolution

User resolution

Role resolution

Project resolution

Site resolution

Active context

Reply context interpretation

Workflow context interpretation

Context precedence policy

Context confidence

Context ambiguity
```

## CONSUMES

```text
NormalizedMessage

UnderstandingResult

Identity interfaces

Project/site query interfaces

Working memory interface

ResolvedContext contract
```

## PRODUCES

```text
ResolvedContext.v1
```

## MUST NOT

```text
Perform raw message parsing

Perform semantic extraction

Select workflows

Execute tools

Create domain records

Send WhatsApp responses
```

---

# 12. Skills Boundary

> Replaces the former "Planner Boundary". There is no planner in v2: the agent chooses tools from the
> skills it is given.

## OWNS

```text
agent_v2/skills/<skill>/SKILL.md   the rules in plain English

agent_v2/skills/<skill>/tools.py   the tool specs the agent may call (reusing existing write paths)

agent_v2/skills/<skill>/evals.yaml the cases that gate the skill before it goes live
```

A new assistant feature is a new skill folder, reviewed with its evals. Today: `general`, `materials`.

## MUST NOT

```text
Create a new write path (skills reuse the toolbox / draft card)

Hold a second copy of a business rule that the domain or toolbox already enforces

Go live before the gate: >= 90% right, 0 wrong saves, reply time not worse than classic
```

---

# 13. Draft and Save Boundary

> Replaces the former "Workflow Runtime Boundary" (LangGraph is dropped). Unchanged from classic agent mode
> and shared by both paths; see [ADR-draft-per-message.md](../architecture/ADR-draft-per-message.md).

## OWNS

```text
The draft card (runtime/agent/draft*.py): lines added by tools

The Save tap: the only thing that writes the card's lines; Cancel removes them

Journal and undo
```

## MUST NOT

```text
Save anything without the Save tap

Let a model or a skill write a record directly
```

---

# 14. Interaction Layer Boundary

## OWNS

```text
Interaction policy

Presentation selection

Text interaction specifications

Button interaction specifications

List interaction specifications

Image/document interaction specifications

Interaction IDs

Interaction correlation

Response interpretation

Interaction expiration behavior
```

## CONSUMES

```text
Workflow state

DraftAction

ResolvedContext

Interaction policies

Channel capabilities
```

## PRODUCES

```text
InteractionSpec.v1

InteractionResponse
```

## MUST NOT

```text
Decide business truth

Write domain records

Execute business commands

Select workflows

Perform semantic understanding

Call provider-specific transport APIs directly
```

Channel-specific rendering belongs to transport adapters.

---

# 15. Memory Boundary

## OWNS

```text
Working memory

Conversation history

Pending workflow state

Relevant structured history retrieval

Semantic retrieval

ContextPack construction

Memory retention policy

Memory access policy
```

## CONSUMES

```text
Memory interfaces

PostgreSQL repositories through adapters

Redis interfaces through adapters

Embedding interfaces

Vector retrieval interfaces
```

## PRODUCES

```text
Working memory state

Conversation memory

Retrieved evidence

ContextPack
```

## MUST NOT

```text
Select workflows

Create domain records

Send messages

Evaluate business rules

Become an unrestricted database query layer

Expose data across tenant boundaries
```

---

# 16. Domain Boundary

The Domain Core is Mesiri's business source of truth.

## OWNS

```text
Organizations

Users and business identity

Projects

Sites

Vendors

Expenses

Approvals

Equipment

Materials

Workforce

Procurement

Timeline business rules

Reports business behavior
```

Each domain owns:

```text
Entities

Value Objects

Commands

Domain Services

Application Use Cases

Repository Interfaces

Domain Errors

Domain Events
```

## CONSUMES

```text
Validated commands

Authenticated actor context

Authorized context

Repository interfaces

Clock interface

Event/outbox interfaces
```

## PRODUCES

```text
Business records

Business results

Domain errors

Domain events
```

## MUST NOT

```text
Depend on WhatsApp payloads

Depend on FastAPI request objects

Depend on LangGraph state

Depend on Gemini response objects

Depend on Redis SDK objects

Depend on SQLAlchemy models as business entities

Depend on provider-specific SDK types
```

The mobile app, dashboard, WhatsApp assistant, API, workers, and scheduler must use the same business/application core.

---

# 17. Platform Boundary

Platform contains reusable Mesiri execution capabilities.

Platform includes:

```text
Tool Registry

Tool Executor

Rules Engine

AI Gateway

Model Router

Idempotency

Authorization

Observability

Scheduling abstractions

Error abstractions
```

Platform capabilities must remain reusable across workflows and services.

Platform must not become a dumping ground for business logic.

Example:

```text
expense approval threshold

→ Domain / Business Rules Definition


generic rule evaluation mechanism

→ Platform Rules Engine
```

---

# 18. Tool Boundary (toolbox)

> Replaces the former "Tool Registry Boundary". The tools are the existing `AgentToolbox` tools plus the
> skills' own tools; v2 calls them, it does not replace them.

## OWNS

```text
runtime/agent/toolbox.py and tools.py: the record tools (labour, work, expense, issue, notes, DPR, materials) and the read tools

Site resolver, unit gate, repeat check: applied inside the tools, not by the agent

Calling the backend handlers through the existing ports
```

## MUST NOT

```text
Be bypassed: a v2 tool that writes goes through the toolbox and the draft card

Contain business rules the domain owns

Give v2 the admin tools (create site / project, members, join code): they stay with classic
```

---

# 19. Rules Engine Boundary

## OWNS

```text
Rule evaluation mechanism

Rule composition

Rule precedence

Rule execution result

Rule telemetry
```

## BUSINESS DOMAINS OWN

```text
Actual business policy definitions

Approval thresholds

Required evidence

Role restrictions

Business constraints
```

The Rules Engine executes policy.

The Domain defines business policy.

---

# 20. Infrastructure Boundary

Infrastructure owns technology-specific implementations.

Examples:

```text
PostgreSQL

Redis

pgvector

Cloudflare R2

Redis Streams

WhatsApp Cloud API

Gemini

DeepSeek

Sarvam

Voyage

OpenTelemetry
```

Infrastructure implements ports/interfaces owned by stable layers.

## MUST NOT

```text
Contain workflow decisions

Contain business rules

Own domain entities

Define product behavior

Become directly imported throughout the codebase
```

Provider SDKs should remain isolated inside infrastructure adapters.

---

# 21. Database Access Boundary

Direct PostgreSQL access is allowed only inside approved persistence adapters.

```text
ALLOWED

Infrastructure repositories

Migration tooling

Transactional application adapters

Outbox implementation

Read-model/query adapters
```

```text
FORBIDDEN

WhatsApp handlers

Understanding pipeline

Planner

Workflow nodes

Interaction layer

LLM prompts

Tool definitions

Frontend applications
```

Required flow:

```text
Caller
   ↓
Application / Domain Interface
   ↓
Repository Port
   ↓
PostgreSQL Adapter
   ↓
Database
```

No module may bypass this path for convenience.

---

# 22. Redis Access Boundary

Direct Redis SDK access is allowed only inside Redis infrastructure adapters.

Approved uses include:

```text
Idempotency

Workflow checkpointing

Pending interaction state

Cache

Rate limiting

Distributed coordination

Event infrastructure
```

Forbidden:

```text
redis.get() inside workflow nodes

redis.set() inside WhatsApp handlers

provider-specific Redis types crossing module boundaries
```

---

# 23. Object Storage Boundary

Direct R2/provider SDK access is restricted to object-storage infrastructure adapters.

Required flow:

```text
Caller
   ↓
Media / ObjectStorage Interface
   ↓
R2 Adapter
   ↓
Cloudflare R2
```

Object keys, bucket names, signed URLs, and provider credentials must not become business-domain concerns.

---

# 24. AI Provider Boundary

Provider SDKs must remain behind AI/provider interfaces.

Required flow:

```text
Understanding / Planner / AI Worker

        ↓

AI Gateway / Provider Port

        ↓

Provider Adapter

        ↓

Gemini / DeepSeek / Sarvam / Voyage
```

Forbidden:

```text
Gemini SDK calls throughout workflow nodes

Sarvam API calls inside WhatsApp service

Voyage SDK calls directly from domain services

DeepSeek response objects becoming shared contracts
```

Provider-specific response objects must be converted into Mesiri-owned contracts before crossing module boundaries.

---

# 25. WhatsApp Provider Boundary

Only the WhatsApp transport adapter may depend on WhatsApp-specific API structures.

Other modules consume Mesiri-owned contracts.

Required:

```text
WhatsApp Payload

        ↓

WhatsApp Adapter

        ↓

NormalizedMessage.v1

        ↓

Mesiri Runtime
```

And outbound:

```text
InteractionSpec

        ↓

WhatsApp Renderer / Delivery Adapter

        ↓

WhatsApp API
```

No workflow should construct WhatsApp API payload JSON directly.

---

# 26. Event Boundary

Domain Services create domain events as part of successful business transactions.

Required persistence path:

```text
Domain Command
        ↓
Domain Service
        ↓
Database Transaction
        ├── Business Record
        └── Outbox Event
```

Event infrastructure owns:

```text
Outbox polling

Publishing

Delivery

Retry

Consumer infrastructure

Dead-letter behavior

Telemetry
```

Consumers own their reaction to events.

Domain services must not depend on Redis Streams directly.

---

# 27. Contract Ownership Rules

Every shared contract has exactly one contract owner.

The contract owner is responsible for:

```text
Schema

Version

Valid fixtures

Invalid fixtures

Compatibility policy

Contract tests

Change history
```

Current ownership:

| Contract               | Owner | Required Reviewer |
| ---------------------- | ----- | ----------------- |
| NormalizedMessage.v1   | Alan  | Ilan              |
| UnderstandingResult.v1 | Ilan  | Alan              |
| ResolvedContext.v1     | TBD   | TBD               |
| CanonicalEvent.v1      | TBD   | TBD               |
| PlannerDecision.v1     | TBD   | TBD               |
| WorkflowState.v1       | TBD   | TBD               |
| RuleResult.v1          | TBD   | TBD               |
| ToolRequest.v1         | TBD   | TBD               |
| ToolResult.v1          | TBD   | TBD               |
| DraftAction.v1         | TBD   | TBD               |
| InteractionSpec.v1     | TBD   | TBD               |
| DomainEvent.v1         | TBD   | TBD               |

A contract owner cannot unilaterally modify a frozen contract.

Affected consumers must approve the change.

---

# 28. M2 → M3 Boundary

This is the current active cross-developer boundary.

```text
ALAN

Raw WhatsApp Payload

        ↓

services/whatsapp

        ↓

NormalizedMessage.v1


================ CONTRACT BOUNDARY ================


ILAN

NormalizedMessage.v1

        ↓

Understanding Pipeline

        ↓

UnderstandingResult.v1
```

Alan guarantees:

```text
schema-valid NormalizedMessage

correct message type

correct external message identity

correct media references

correct reply context

correct interactive response data

deduplication behavior

correlation ID presence
```

Ilan guarantees:

```text
acceptance of every valid NormalizedMessage fixture

no dependence on raw WhatsApp payloads

correct modality routing

provider failures handled

schema-valid UnderstandingResult

correlation ID propagation
```

Integration must require no permanent transformation glue.

---

# 29. Shared Fixture Ownership

Shared contract fixtures live in:

```text
scenarios/contracts/
```

Example:

```text
scenarios/contracts/m2_to_m3/

valid/
    text_message.json
    image_message.json
    voice_message.json
    button_response.json
    list_response.json
    reply_message.json

invalid/
    missing_message_id.json
    invalid_message_type.json
    malformed_media.json
```

Rules:

```text
Producer creates fixtures.

Consumer reviews fixtures.

Producer contract tests emit compatible data.

Consumer contract tests consume the same fixtures.

Frozen fixtures cannot change without contract review.
```

---

# 30. Scenario Ownership

Every scenario has one primary owner.

Cross-service scenarios may have multiple contributors but still require one accountable owner.

The owner is responsible for:

```text
Scenario specification

Fixtures

Test automation

Execution

Evidence

Failure tracking

Gate reporting
```

Example:

```text
SCN-004 Duplicate Webhook

Owner: Alan

Reviewer: Ilan
```

```text
SCN-009 Model Timeout and Fallback

Owner: Ilan

Reviewer: Alan
```

---

# 31. Test Ownership

The owner of production code owns its tests.

Required:

```text
Module owner
    ↓
Unit Tests

Contract owner
    ↓
Contract Tests + Fixtures

Adapter owner
    ↓
Integration Tests

Scenario owner
    ↓
Scenario Tests

Milestone owner
    ↓
Gate Tests + Evidence
```

A reviewer may request additional tests when shared behavior is insufficiently protected.

---

# 32. Cross-Boundary Change Rule

A change is cross-boundary when it affects:

```text
Shared contract

Public interface

Consumed behavior

Dependency direction

Database ownership

Infrastructure access

Authentication

Authorization

Event behavior

Workflow/domain responsibility

Integration gate
```

Required process:

```text
Change Identified
        ↓
Affected Owners Identified
        ↓
Impact Documented
        ↓
Change Request Created if Required
        ↓
Owner Approval
        ↓
Reviewer Approval
        ↓
Implementation
        ↓
Tests Updated
        ↓
Integration Verification
```

No silent cross-boundary changes.

---

# 33. Temporary Cross-Module Work

A developer may temporarily work inside another owner's module only when:

```text
Primary owner agrees.

Scope is explicitly defined.

PR names the affected owner.

Affected owner reviews the PR.

No ownership transfer is implied.
```

Example:

```text
Ilan needs a media adapter method for M3.

Alan agrees Ilan may add the interface-compatible method.

Alan reviews the PR.

WhatsApp ownership remains with Alan.
```

---

# 34. Ownership Transfer

Ownership may change between milestones.

Required process:

```text
Current Owner

        ↓

Handover Document / PR

        ↓

Open Risks Recorded

        ↓

Public Interfaces Reviewed

        ↓

Tests Passing

        ↓

New Owner Accepts

        ↓

Ownership Registry Updated
```

Ownership transfer does not happen implicitly because another developer wrote the most recent code.

---

# 35. Conflict Resolution

When developers disagree:

## IMPLEMENTATION DETAIL

Primary owner decides.

Provided contracts and architecture boundaries are respected.

---

## SHARED CONTRACT

Producer and consumer must agree.

If agreement cannot be reached:

```text
Record alternatives.

Record compatibility impact.

Record migration cost.

Choose through ADR.
```

---

## ARCHITECTURE BOUNDARY

Both developers must approve.

If unresolved:

```text
Stop affected implementation.

Create ADR.

Compare options against:

correctness

complexity

coupling

operational cost

migration cost

testability

reversibility

Then decide.
```

Do not allow architecture disagreements to become hidden implementation divergence.

---

# 36. Boundary Violation Examples

## INVALID

```text
services/assistant/workflows/expense/nodes.py

import psycopg
```

Reason:

Workflow directly accesses PostgreSQL.

---

## VALID

```text
Workflow

    ↓

ExpenseApplicationService

    ↓

ExpenseRepository Port

    ↓

PostgreSQL ExpenseRepository
```

---

## INVALID

```text
services/whatsapp/webhook.py

gemini.generate_content(...)
```

Reason:

Transport service performs semantic understanding.

---

## VALID

```text
WhatsApp Service

    ↓

NormalizedMessage

    ↓

Understanding Pipeline

    ↓

AI Gateway

    ↓

Gemini Adapter
```

---

## INVALID

```text
Understanding Pipeline

    ↓

expense_repository.insert(...)
```

Reason:

Understanding creates business records.

---

## INVALID

```text
LangGraph Node

    ↓

WhatsApp API Payload JSON
```

Reason:

Workflow depends on transport implementation.

---

## VALID

```text
LangGraph Node

    ↓

Interaction Request

    ↓

InteractionSpec

    ↓

WhatsApp Renderer

    ↓

WhatsApp API
```

---

# 37. Automated Boundary Enforcement

Architecture boundaries should be enforced by tests and tooling where practical.

Recommended checks:

```text
No infrastructure SDK imports in domain modules.

No WhatsApp SDK imports outside WhatsApp adapters.

No AI provider SDK imports outside provider adapters.

No direct PostgreSQL access from assistant modules.

No direct Redis access from workflows.

No domain imports from infrastructure into domain.

No generated contract files manually modified.

No circular service/module dependencies.
```

Possible enforcement mechanisms:

```text
import-linter

Ruff custom rules

dependency-cruiser for TypeScript

CODEOWNERS

CI path checks

architecture contract tests
```

Automation is preferred over relying only on developer memory.

---

# 38. Recommended CODEOWNERS Rules

Example:

```text
# WhatsApp Service

/services/whatsapp/                         @alan


# Understanding Pipeline

/services/assistant/**/understanding/       @ilan


# Contracts

/packages/contracts/                        @ilan @alan

/scenarios/contracts/                       @ilan @alan


# Domain Core

/services/domain/                           @ilan @alan


# Platform Capabilities

/services/platform/                         @ilan @alan


# Infrastructure Adapters

/services/infrastructure/                   @ilan @alan


# Execution Control Documents

/docs/execution/                            @ilan @alan


# Architecture Decisions

/docs/decisions/                            @ilan @alan


# Database Migrations

/packages/database/migrations/              @ilan @alan


# Infrastructure as Code

/infrastructure/                            @ilan @alan
```

Replace GitHub usernames with actual account names.

CODEOWNERS does not replace the ownership rules in this document.

---

# 39. Current Boundary Risks

## RISK-001 — Assistant Becomes a God Service

Risk:

```text
Understanding
Context
Planner
Workflow
Tools
Rules
Domain Logic
Database Access
Provider Access
WhatsApp Rendering

all implemented inside services/assistant.
```

Mitigation:

Strict Domain, Platform, Infrastructure, and Transport boundaries.

---

## RISK-002 — Duplicate Business Logic

Risk:

Expense/project/material logic implemented independently in:

```text
API

Mobile backend handlers

WhatsApp assistant

Workers
```

Mitigation:

All surfaces use the same Domain/Application Core.

---

## RISK-003 — Provider Leakage

Risk:

Gemini, Sarvam, DeepSeek, Voyage, WhatsApp, Redis, and PostgreSQL SDK objects spread across the codebase.

Mitigation:

Provider adapters and Mesiri-owned contracts.

---

## RISK-004 — Contract Drift During Parallel Development

Risk:

Alan changes M2 output while Ilan builds M3 against an older shape.

Mitigation:

Frozen contracts, shared fixtures, contract tests, required cross-review.

---

## RISK-005 — Hidden Integration Glue

Risk:

Integration succeeds only because mapping code silently translates incompatible implementations.

Mitigation:

M2 real output must directly validate against the same contract fixtures consumed by M3.

Permanent glue code requires architectural justification.

---

# 40. Current Required Actions

## Shared

* [ ] Approve this ownership document.
* [ ] Replace placeholder CODEOWNERS usernames.
* [ ] Assign M1 owner and reviewer.
* [ ] Approve M2 ownership.
* [ ] Approve M3 ownership.
* [ ] Freeze `NormalizedMessage.v1`.
* [ ] Approve `UnderstandingResult.v1`.
* [ ] Create shared M2 → M3 fixtures.
* [ ] Add architecture boundary checks to CI.
* [ ] Record future milestone ownership before activation.

---

# 41. Approval Checklist

Before this document becomes `APPROVED`:

```text
[ ] Both developers agree on current ownership.

[ ] Both developers agree on M2 → M3 boundary.

[ ] Both developers agree on Domain boundary.

[ ] Both developers agree on Platform boundary.

[ ] Both developers agree on Infrastructure boundary.

[ ] Both developers agree on database access rules.

[ ] Both developers agree on Redis access rules.

[ ] Both developers agree on provider access rules.

[ ] Both developers agree on contract ownership rules.

[ ] Both developers agree on cross-boundary change process.

[ ] Both developers agree on conflict-resolution process.

[ ] CODEOWNERS paths match the actual repository.

[ ] Automated boundary checks have an implementation owner.
```

---

# 42. Final Rule

The repository structure alone does not protect the architecture.

The operational rule is:

```text
Every module has one clear responsibility.

Every active module has one primary owner.

Every shared boundary has an explicit contract.

Every contract has an owner and consumer.

Every infrastructure dependency is accessed through an approved interface.

Every business write passes through the Domain/Application Core.

Every cross-boundary change is reviewed.

Every milestone ends with integration evidence.
```

If code violates these rules, it is considered an architecture defect even if the feature appears to work.
