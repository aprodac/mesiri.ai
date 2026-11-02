# Semantic search over saved records (BE-52)

> Plan, 2 Nov 2026 (Claude, session with Adarsh). **Status: blocked, waiting for Alan's approval**
> (security-sensitive: a new read path over every company's records; and an ops change to the
> Postgres image for step 2). Nothing here is built yet.
> Based on `main` at `faf869a8`. Production and the WhatsApp groups were **not** read (the ops and
> teammate tokens were not available in the session), so the problem evidence below comes from
> last week's tracker rows and commits, not from customer messages.

## 1. Why: what went wrong last week (26 Oct - 2 Nov)

The same class kept coming back: people write and speak in Malayalam / Manglish / site slang, our
records are in English, and each time a hand-kept table or a prompt dump papered over it.

| Problem | Where | Patch | Why it does not scale |
|---|---|---|---|
| "kambi" did not find Steel | request 165, WA-127 | local-word table, `material_aliases`, transliteration | every new word is a manual entry |
| a new material close to a listed one | request 159 part D | "Same as ...?" on spelling closeness | "Cement bag" vs "OPC 53" share no letters |
| which open issue "crane is working now" means | `runtime/agent/issue_match.py` | stop words + `_TYPE_WORDS` table | a word list, which `CLAUDE.md` forbids adding to |
| "did anyone report X?" | WA-127 | today's newest 40 timeline rows in the prompt | nothing older than today can be answered |
| "group for hospital project" | WA-87 | a special project-name lookup | same class: loose words to a record |

Not this class (search would not have helped): request 202 (stock read scoped to one project),
request 137 (UTC vs project day), request 195 (unit conversion).

## 2. What already exists (reuse, do not duplicate)

| Piece | Where | Use |
|---|---|---|
| Words people wrote | `activities.narrative`, `progress_updates.narrative`, `site_issues.narrative` + `resolution_notes`, `progress_attachments.caption` + `ai_caption`, `expenses.description`, material `notes` | the text to index (original language, often Manglish; agent saves cut it to 160 chars) |
| English of the message | `inbound_messages.body_text_en`, joined by `correlation_id` | indexed next to the original |
| Timeline | `timeline_entries` (`events/consumers/timeline_projector.py`) | **not enough alone**: summaries are templates ("Weather reported") without the user's words |
| Event bus | `events/bus/dispatcher.py`, `event_consumer_checkpoints` (0450) | the "#17 Search Index" consumer it was designed for; `run_event_consumers.py` has no consumer and no systemd timer yet |
| Tenant isolation | RLS policy `tenant_isolation` (0484), `infrastructure/postgres/tenant.py` | same policy on the new table |
| Project / site scope | `domains/timeline/router.py` `_resolve_project_ids`, `_site_filter_denied` | same scoping for `/search` |
| Who sees money | `authorization/roles.py` `may_view_expenses` (SEC-01) | expense rows only for those roles |
| AI providers + cost | `platform/ai` resolver, Gemini key, `application/usage/recorder.py` | embeddings via Gemini, costed automatically; no new vendor |
| v3 tools | `apps/whatsapp-assistant/src/agent_api/tools.py` `ALLOWED`, built from OpenAPI | `GET /search` becomes the v3 tool and a dashboard feature at once |
| Postgres | `postgres:16-alpine` (`infra/docker-compose.prod.yml`) | `pg_trgm` + full-text available; **pgvector is not** |

## 3. Design

```
record saved -> outbox_events -> SearchIndexConsumer (#17, every minute)
                                   reads the source row + English text by correlation_id
                                   -> search_documents (text now, embedding NULL)
                 embed job (same timer, after the drain): fills NULL embeddings in batches
GET /search?q=&project_id=&site_id=&date_from=&date_to=&kinds=  -> hybrid SQL -> dashboard + v3 tool
```

### 3.1 Table (one additive migration, next free number at the time)

```
search_documents(
  id uuid pk, organization_id, project_id, site_id,
  kind            work | progress | issue | photo | material | expense
  source_type, source_id            UNIQUE (source_type, source_id)
  occurred_on date                  the project's day (day_facts.project_date_sql rule)
  text_original, text_en,
  tsv tsvector GENERATED ('simple' config: no English stemming of Manglish),
  embedding vector(768) NULL, embed_model, content_hash,
  is_hidden bool                    withdrawn / voided / reversed
)
```

Indexes: B-tree `(organization_id, occurred_on)`, GIN on `tsv`, trigram GIN on the text.
RLS: `tenant_isolation`, as 0484. No module table is changed.

### 3.2 Keeping it current

- `SearchIndexConsumer` registered in `run_event_consumers.py`; new tracked
  `infra/mesiri-search-index.{service,timer}` (copy of `mesiri-timeline`), enabled by `deploy.yml`.
- Created / corrected / voided / cancelled / reversed events upsert the row or set `is_hidden`.
- **No AI call inside the consumer transaction**; it writes text only, so keyword search works
  within a minute. The embed job fills embeddings afterwards; a Gemini failure blocks nothing.
- `backfill_search_documents` script for existing rows; re-runnable (`content_hash`).

### 3.3 Query

Filter first, in SQL: company, allowed `project_ids`, site, dates, `NOT is_hidden`, and
`kind <> 'expense'` unless `may_view_expenses(role)`. Then rank by full-text, trigram and (step 2)
cosine, merged with reciprocal rank fusion. No ANN index in V1: a company has thousands of rows,
an exact scan after the company filter is fast and never drops a hit (HNSW later if needed).
If the query embedding fails or times out, keyword ranking alone answers.

### 3.4 Embeddings (step 2)

New `EmbeddingProvider` port in `platform/ai/ports/`, an `embedding` capability in the resolver,
Gemini adapter, 768 dimensions, original + English embedded together.

### 3.5 Where it is used

- v3: `search_records` added to `ALLOWED`, one `SOP.md` line ("questions about earlier days"),
  scripted test in `tests/agent_api/`.
- Dashboard: a search box on Site log.
- Classic: no change (no new features there).
- Later (step 3): candidate materials / issues from the same search, always confirmed by the user;
  worker names stay exact-only (`workforce/matching.py`).

Labour / attendance / wages are **not indexed** in V1 (Module Isolation).

## 4. Steps

| Step | What | New infrastructure | Gate |
|---|---|---|---|
| 0 | 50-100 real questions and bad matches from production + groups -> eval set | none | ops + teammate tokens |
| 1 | table, consumer, timer, backfill, `GET /search` (FTS + trigram + English text), v3 tool | none | **Alan** (tenant data, permissions) |
| 2 | pgvector, embedding port, embed job, hybrid ranking | custom Postgres image | **ops + Alan** |
| 3 | candidate suggestions for materials / issues | none | product decision |

Measure after each step (right record in top 5, added reply time). Go to step 2 only if step 1
misses on the eval set.

## 5. Risks

1. **Postgres image.** Do not switch to `pgvector/pgvector:pg16`: it is Debian (glibc), the
   current image is Alpine (musl); text-index collation can differ silently and need `REINDEX`.
   Build `FROM postgres:16-alpine` and compile pgvector into it. Backup first.
2. **No event-consumer timer exists**; the runner's cron is "ops-managed, not tracked". Step 1
   adds a tracked systemd timer.
3. **Stored text is Manglish**; without `text_en` (step 1) or embeddings (step 2) an English
   question will not find it.
4. **Reply time**: one embedding call on the request path, with a timeout and keyword fallback.
5. **Permissions**: a search result can leak what its source page hides; the money rule must be
   applied in the SQL, not after.

## 6. Found while planning (separate item, SEC-02)

`GET /timeline` (`domains/timeline/router.py`) and the v3 `timeline` tool
(`agent_api/tools.py`) return `ExpenseRecorded` ("INR 5000 expense recorded") and
`MoneyTransactionTransferred` rows to **every** role in project scope, without the
`may_view_expenses` check SEC-01 set. Found in code only; not checked against production.

## 7. Testing

- Consumer unit tests per event kind, including undo / void.
- Postgres integration: company A never sees company B (RLS and the project filter); a site
  engineer never sees expense rows.
- `tests/agent_api/`: an English question finds a Manglish record, a sibling, and the guard that
  worker names are never fuzzy-matched.
- Recall@5 script over the eval set; full `CLAUDE.md` verification before any push.

## 8. Rollback

Company setting `search.enabled` (default off) gates the route and the tool; remove `search_records`
from `ALLOWED`; migration downgrade drops the table; disable the timer. Step 2: `DROP EXTENSION
vector`, then the previous image.

## 9. Success criteria

Right record in the top 5 for at least 80% of the eval set; zero cross-company or cross-role
results; under 300 ms added to the reply.
