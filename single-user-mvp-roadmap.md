# Revero single-user production MVP roadmap

Status: proposed implementation plan; no milestone is complete merely because it is described here.

Prepared: 16 November 2026. Owner and initial user: one person. Build on the existing application; do not rewrite it.

## 1. Outcome and operating principles

Revero should reliably remember why you saved a Reel, help you find it later, and bring it back when useful. Production quality for this release means durable data, bounded costs, visible failures, and demonstrated recovery. It does not mean that external platforms never fail.

The release must support:

- Capture through the web app and Telegram, with Instagram as an additional channel.
- An optional personal note attached to every save.
- Search by wording, intent, and supported date filters without requiring an LLM.
- Library-wide resurfacing at one configurable daily time, plus manual delivery.
- Explicit feedback, small action tracking, and confirmed deadlines.
- Inspection and recovery of blocked, deferred, failed, and uncertain operations.
- Export, deletion, automatic backups, and tested restoration.

Keep FastAPI, React/Vite, SQLite, and existing durable job/delivery behavior. Prefer small changes behind stable interfaces. Preserve existing evidence validation and duplicate protection while improving the product loop.

Core invariant: a provider outage must not prevent saving, browsing, editing notes, or lexical search.

## 2. Scope boundaries

### Required for this MVP

1. One private owner; unauthorized senders cannot ingest, query, or trigger delivery.
2. Always-on deployment with persistent storage and private workspace access.
3. Durable intake and acknowledgements, notes, provenance, and deduplication.
4. Provider quota accounting and bounded retries.
5. Measured retrieval and library-wide resurfacing.
6. Recovery controls, backup/restore, export/delete, and a two-week personal trial.

### Deferred

Public registration, payments, multiple tenants, WhatsApp, learned ranking, automatic video downloading, calendar synchronization, shared libraries, and mobile/browser extensions are outside this release.

Existing uploaded-video processing remains optional and experimental. It must not consume default processing capacity or block the core release. Do not remove working functionality merely to simplify the roadmap.

## 3. Current foundations and facts to verify

Source inspection has identified these foundations:

| Area | Existing location | Implication |
| --- | --- | --- |
| Worker and scheduler | `backend/app/worker.py` | Scheduler checks run separately from extraction work. |
| Extraction jobs and SQLite access | `backend/app/extraction.py` | Persistent jobs and leases already exist; SQLite connections use a 15-second timeout. |
| Digest storage, scheduler, sender | `backend/app/digest.py` | Configurable time, manual runs, retries, and uncertain delivery already exist. |
| Digest UI | `frontend/src/DigestView.jsx` | Delivery-time input and Send digest now button already exist. |
| API initialization | `backend/app/main.py` | Existing initialization must be transitioned safely to explicit migrations. |
| Retrieval | `backend/app/search.py` | Audit actual indexed evidence before changing retrieval. |
| Instagram integration | `backend/app/instagram.py`, `backend/app/instagram_webhook.py`, `backend/app/instagram_worker.py` | Preserve signature validation, deduplication, and durable replies. |
| Existing coverage | `backend/tests/`, `frontend/tests/` | Extend behavioral tests rather than replacing them. |

Previous onboarding ran 129 backend tests, 11 browser tests, and a production build successfully. That is historical baseline evidence, not proof of future commits or live-provider behavior.

The supplied gap analysis was based on documentation rather than a source audit. Treat its assertions as hypotheses until checked. In particular, confirm WAL configuration, quota accounting, current search fields, migrations, and deployment behavior.

## 4. Architecture decisions

### Deployment

Use one persistent Linux VM, initially sized around 2 vCPU and 4 GB RAM, subject to measured embedding-model memory. Use Docker Compose or an equivalent simple supervisor for restart policies and reproducibility. Avoid Kubernetes, Redis, and separate microservices.

Run separate supervised processes for the private API, ingestion as needed, background processing, and delivery scheduling. Keep business rules in shared application modules. The exact process split should preserve fault isolation without duplicating scheduling ownership.

Expose only the Instagram webhook through a stable HTTPS endpoint. Keep the workspace/API private through a VPN or identity-aware gateway. Start Telegram intake with long polling and a single active consumer. Long polling state must survive process restarts.

Use SQLite WAL on local persistent disk, foreign keys, a busy timeout, short transactions, and explicit migrations. Never hold a database write transaction across an external HTTP request. Do not place SQLite on a network filesystem as a scaling shortcut.

### Logical boundaries

- Intake adapters: authenticate, validate, normalize, and hand off events.
- Library service: canonical saves, notes, provenance, deletion, and ownership.
- Retrieval service: index revisions, lexical/vector retrieval, result fusion.
- Enrichment service: optional model processing and evidence validation.
- Provider gateway: request reservations, quotas, budgets, timeouts, and accounting.
- Scheduling service: due runs, missed-run policy, and eligibility.
- Delivery service: immutable snapshots, multipart progress, retries, uncertainty.
- Storage layer: transaction boundaries and migrations.
- Operations: health, backups, recovery, and audit events.

Introduce these boundaries incrementally; do not turn the first milestone into a wholesale file reorganization.

### Ownership and future expansion

Represent the single owner explicitly in configuration and service calls. New ownership-bearing records should have an unambiguous owner relationship. Avoid an invasive migration of every existing table solely for hypothetical scaling. Before adding a second user, require a complete ownership migration, authenticated identity mapping, and isolation tests across every query and job.

## 5. Data and state contracts

### Save and content contract

Persist canonical URL/platform ID, source channel, saved time, source event identity, notes, and content provenance. Deduplicate source events independently from saves. Sharing the same Reel again should locate the existing save and allow another note.

Keep supplied captions, user notes, uploaded evidence, and model-derived text distinguishable. Record acquisition time and content revision. Useful content-quality states include link-only, note-available, caption-available, and uploaded-evidence-available.

### Additional records

Introduce only as needed by milestones:

- Notes and provenance records.
- Versioned search documents and embeddings.
- Date hints with source wording, anchor, candidate window, and confirmation status.
- Surfacing selections, reasons, and feedback events.
- Provider-call ledger and quota reservations.
- Versioned settings and migration history.
- Operational audit events without secret or private-content dumps.

Derived indexes must be rebuildable from authoritative records. Deletion must invalidate all associated derived state.

### Job outcomes

| State | Meaning | Recovery |
| --- | --- | --- |
| Queued | Eligible work awaiting claim | Worker claims atomically. |
| Running | Claimed with lease and attempt identity | Renew lease or recover after expiry. |
| Deferred | Waiting for quota, budget, or cooldown | Resume at recorded eligible time. |
| Retryable failure | Temporary error | Bounded retry with jitter. |
| Blocked | Credentials/configuration need attention | Explicit repair and retry. |
| Permanent failure | Invalid input or exhausted recovery | Inspect, amend input, or abandon. |
| Succeeded | Result committed | Duplicate execution returns existing result. |
| Cancelled | Work intentionally stopped | Cannot re-enter execution automatically. |

Migration must map existing states explicitly. Do not change enum strings without updating queries, UI, and recovery paths together.

### Delivery contract

External messaging cannot be guaranteed exactly once. Preserve confirmed message IDs and part-level progress. Retry clear failures, but mark ambiguous outcomes uncertain and require review before resending. An acknowledgement means the save committed, not that enrichment finished.

## 6. Milestones and work packages

Milestones are dependency gates, not calendar promises. A focused solo implementation may take roughly six to nine weeks; revise after the baseline audit. Each work package should be independently reviewable and include its migration, behavior tests, and operational notes where applicable.

### M0 — Establish an executable baseline

**Purpose:** identify actual defects and preserve working behavior before architectural changes.

Tasks:

1. Record the selected commit, runtime versions, dependency locks, and startup commands.
2. Map intake → storage → processing → retrieval → scheduling → delivery using actual functions and tables.
3. Audit job claims, transaction scopes, quota counters, retry policies, and scheduler ownership.
4. Inventory environment variables by name and purpose; do not copy secret values.
5. Confirm what search indexes and what content real shares supply.
6. Run the backend suite, browser suite, and production build in a reproducible environment.
7. Create a prioritized defect register with evidence, reproduction, affected invariant, and proposed fix.
8. Verify current official Meta permissions, Telegram limits, Gemini quotas/data terms, and candidate hosting costs. Record URLs and verification dates.

Deliverables: baseline report, dependency/state map, defect register, and short architecture decision records.

Exit gate: tests are reproducible; failures are explained; no source-audit claim relies only on README wording.

### M1 — Protect data and make deployment recoverable

**Depends on:** M0.

Tasks:

1. Add explicit, ordered schema migrations with a schema-version table.
2. Test upgrades from representative existing databases; preserve saves and delivery records.
3. Initialize WAL, foreign keys, and busy handling consistently.
4. Introduce deployment configuration with persistent volumes, health checks, restart policies, and secrets supplied outside the image.
5. Secure private workspace access and restrict public ingress to required webhook routes.
6. Add structured, redacted logs and worker heartbeat/queue-age checks.
7. Implement consistent encrypted off-host backups and retention.
8. Document and execute a clean-host restore drill, including suppression of accidental replayed deliveries.
9. Add CI for tests/build and migration checks without real provider credentials.

Exit gate: host/process restarts preserve data; concurrent writes are tested; backup restoration works; no credentials appear in logs. Proposed recovery objectives are at most one hour of data loss and restoration within two hours, demonstrated in a drill.

Do not claim readiness from a container being up or a port being open. Verify representative application operations.

### M2 — Make capture dependable and independent of Meta

**Depends on:** M1.

Tasks:

1. Extract a shared save operation used by web, Instagram, and Telegram.
2. Persist the source event, canonical save, and acknowledgement intent transactionally.
3. Add Telegram long-poll ingestion with durable update progress and a single-consumer rule.
4. Authorize the configured owner/chat before processing commands, URLs, or callbacks.
5. Add optional notes during capture and editing in the web app.
6. Make duplicate shares resolve to the existing save while permitting new notes.
7. Preserve the signed Instagram webhook and configure a stable callback address.
8. Expose clear link-only/content-needed status instead of inventing summaries.

Exit gate: replaying inbound events produces one save and no uncontrolled acknowledgement duplication; a crash after commit does not lose the acknowledgement intent; unauthorized users are rejected; Telegram and web remain useful during Meta outage.

### M3 — Bound provider calls and recover work safely

**Depends on:** M1; can follow M2 without waiting for retrieval work.

Tasks:

1. Route every Gemini operation, including Ask and retries, through one provider gateway.
2. Create persistent request/token reservations and an attempt ledger.
3. Account at the provider's real quota scope; batches count as HTTP requests while retaining their token costs.
4. Add deferred and blocked outcomes with explicit UI explanations.
5. Honor Retry-After and provider reset semantics; use bounded jittered backoff and circuit breaking.
6. Separate ordinary retry attempts from quota waiting.
7. Preserve ambiguous usage after a crash conservatively rather than assuming an unrecorded request was free.
8. Disable automatic paid fallback; require an explicit budget to enable paid processing.
9. Add recovery controls for retry, cancel, and configuration repair.

Exit gate: quota exhaustion survives restarts without becoming permanent failure; concurrent callers cannot exceed locally reserved capacity; repeated provider failures cannot create an unbounded retry/spend loop; saving and search continue without Gemini.

### M4 — Build measured recall

**Depends on:** M2; optional model-based answers also depend on M3.

Tasks:

1. Build a real evaluation set of 30–50 queries with expected saves and unanswerable cases.
2. Reserve a held-out subset before tuning.
3. Improve FTS indexing of notes, captions, titles, and validated evidence.
4. Add explicit date/topic/action filters and preserve provenance in snippets.
5. Benchmark small local multilingual embedding models for quality, license, latency, and peak memory.
6. Pin the chosen model revision; store vector model/content revisions.
7. Implement exact vector comparison for the initial library and combine results with lexical ranking using reciprocal rank fusion.
8. Reindex only changed content; support resumable rebuild and lexical fallback.
9. Return relevant links/snippets before offering optional generated explanation.

Exit gate: proposed target of at least 85% hit@3 on answerable held-out queries; hybrid improves paraphrase queries without material exact-match regression; no-match results are honest; ordinary search makes no Gemini request. Report actual results, including weak language/query categories.

### M5 — Deliver useful resurfacing and feedback

**Depends on:** M2 and M4; reliable delivery foundations from M1/M3.

Tasks:

1. Generate candidates across the full library rather than only today's saves.
2. Prioritize confirmed deadlines, due snoozes, useful older items, and relevant recent items.
3. Apply deletion/dismissal/snooze/cooldown exclusions before ranking.
4. Select up to three diverse items with deterministic, inspectable reasons.
5. Store selections and frozen message content per run; retries reuse the snapshot.
6. Keep manual and scheduled delivery histories separate.
7. Define timezone, time-change, grace-window, and missed-run semantics explicitly.
8. Add idempotent snooze, not-useful, and action-complete feedback callbacks.
9. Show next scheduled delivery, disabled state, last result, and uncertainty in the UI.
10. Keep ambiguous dates in a review flow; do not turn creator-relative wording into confirmed deadlines.

Exit gate: useful older saves appear on days without new saves; completed runs do not resend after settings changes; missed runs follow the documented grace policy; manual delivery does not consume scheduled delivery; uncertain multipart delivery requires review; feedback changes future eligibility predictably.

When no eligible useful items exist, record a skipped run and send no routine digest. Do not manufacture content to fill three slots.

### M6 — Finish personal control and daily operations

**Depends on:** M2–M5 data contracts.

Tasks:

1. Export authoritative data in a documented portable format with timestamps and provenance.
2. Delete a save and all active derived content, vectors, pending jobs, and temporary media.
3. Define deletion behavior for already-sent Telegram messages and retained backups; do not imply they are automatically erased.
4. Complete the operations screen for queue age, credentials status, deferred work, failures, uncertainty, backup age, and storage pressure.
5. Add appropriate upload limits, media-processing bounds, cleanup, and request validation.
6. Document deployment, upgrade, rollback, restore, token repair, and quota recovery procedures.
7. Confirm model/provider privacy settings and acceptable terms for personal use.

Exit gate: deletion cannot resurrect through a queued job; export is readable and complete; restore does not accidentally resend historic messages; recovery procedures are executable by the owner without database surgery.

### M7 — Prove the MVP in a two-week personal trial

**Depends on:** all previous exit gates.

Use the real library daily. Record useful retrievals, missed retrievals, useful resurfacing, ignored items, manual interventions, queue delays, provider usage, and actual costs. Compare resurfacing against a simple newest-first baseline without claiming statistical significance from one user.

Inject and document controlled failures:

- Gemini unavailable and quota exhausted.
- Invalid or expired Meta configuration.
- Telegram timeout after possible acceptance.
- Worker termination before/after external calls and database commits.
- Restart near scheduled delivery, midnight, and after the grace window.
- Concurrent manual sends and schedule changes.
- Disk-space pressure and backup failure.
- Restore into an isolated environment.
- Delete while indexing or delivery is queued.
- Several days without new saves.

Exit gate: no unexplained loss of committed saves, no uncontrolled duplicate-delivery behavior, bounded calls/cost, successful recovery drills, and useful recall/resurfacing demonstrated on personal data. Every remaining limitation is visible and documented.

## 7. Test strategy

Use four complementary layers:

1. Unit tests for ranking, date interpretation, quota transitions, and state rules.
2. Integration tests with temporary databases for migrations, transactions, leases, deduplication, cancellation, and restart recovery.
3. Browser tests for capture, note editing, search, schedule settings, manual send, feedback, export/delete, and recovery UI.
4. Controlled live smoke tests for actual provider configuration after offline tests pass.

Use fake clocks and injected providers for deterministic failure tests. Avoid spending real quota in CI. Preserve the underlying command exit status and distinguish pass, fail, skip, and unrun outcomes.

A live message test must be deliberate and identifiable. Do not use real delivery as an incidental health probe.

## 8. Cost and external dependency policy

Planning allowance: approximately INR 1,000–2,500 monthly for hosting, backup, and incidental infrastructure; obtain actual quotes before purchase. Start with zero authorized paid LLM usage. This allowance is not a verified price commitment.

Measure compute memory, database/index growth, backup storage, provider attempts, tokens where exposed, and weekly spending. Search, capture, ranking, and formatting must not require paid inference.

Do not assume free-tier limits or reset times from historic observations. Store configuration separately from provider implementation and record verified limits. No silent paid fallback, model rotation to evade limits, or scraping workaround for missing Meta permissions.

## 9. Security and privacy checklist for release

- One authorized owner for UI access and inbound channel actions.
- Webhook verification before accepting work; bounded request bodies.
- Secrets absent from repository, images, exports, and logs.
- Private APIs protected by the selected access layer, with appropriate session/CSRF controls.
- No arbitrary server-side URL fetching from submitted links.
- Temporary uploads bounded and cleaned up.
- Model-derived assertions labeled; dates require confirmation.
- Backup encryption, retention, access restriction, and restore verification.
- Export/delete behavior and backup retention documented.

This is a release checklist, not a claim of formal security certification.

## 10. Future migration paths

| Trigger | Future change | Preparation now |
| --- | --- | --- |
| Second user | Authenticated identities and complete tenant isolation | Explicit owner boundaries and stable IDs |
| Multiple app instances or sustained write contention | PostgreSQL and transactional job claims | Storage interfaces and explicit transactions |
| Measured vector search bottleneck | pgvector or another suitable index | Versioned embedding records and retrieval interface |
| Worker backlog beyond one machine | Separate worker pools and fair scheduling | Durable leases, idempotency, bounded jobs |
| Additional channels | New intake/delivery adapters | Shared save and delivery services |
| Paid plans | Per-user quotas, accounting, billing | Provider ledger and cost controls |

Do not migrate on an arbitrary user-count threshold. Before public users, separately review privacy obligations, provider terms, Meta access requirements, abuse prevention, and data isolation.

## 11. First work package: start here

The first implementation task should complete M0 and prepare M1, not add another feature.

1. Create `docs/baseline-audit.md` with the inspected commit, architecture map, actual table/state inventory, and reproducible commands.
2. Re-run existing tests/build and record results.
3. Produce a defect table with priority, evidence, reproduction, and acceptance test.
4. Decide and document the migration mechanism, deployment/access choice, backup destination/retention, and provider budget policy.
5. Implement explicit migrations and migration tests as the first code change.
6. Add backup and isolated restore verification before modifying authoritative data structures for notes or search.

Suggested subsequent change sequence:

- Change 1: baseline evidence and decision records.
- Change 2: migrations and existing-database upgrade coverage.
- Change 3: backup/restore and deployment supervision.
- Change 4: shared intake, Telegram, and notes.
- Change 5: provider accounting and deferred recovery.
- Change 6: measured retrieval.
- Change 7: resurfacing and feedback.
- Change 8: export/delete and operational controls.
- Change 9: trial findings and targeted fixes.

Each change should explain the concrete behavior, migration implications, tests, rollback/recovery approach, and remaining limitations. Keep unrelated cleanup separate.

## 12. Milestone tracking template

For each milestone, maintain:

- Status: not started / active / blocked / verified.
- Owner and target date.
- Dependencies and unresolved decisions.
- Work items and associated commits or review links.
- Acceptance evidence and commands executed.
- Known failures, skipped checks, and external blockers.
- Operational documentation updated.
- Explicit exit decision.

A milestone is verified only when its exit evidence exists. Shipping the code, seeing a green health indicator, or writing the runbook is insufficient on its own.
