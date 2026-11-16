# M0 architecture decision records

Date: 2026-11-16. Scope: proposals and constraints for owner review; **no deployment, storage, schema, budget, or provider changes are authorized by this document**. Superseding roadmap: root `single-user-mvp-roadmap.md`. The user must explicitly approve M1 before any implementation.

## ADR-001 — Versioned SQLite upgrades

Status: **proposed, not implemented; owner review pending**.

Keep SQLite and the existing authoritative records. Recommend small numbered Python migration functions using sqlite3, an ordered `schema_migrations(version, checksum, applied_at)` history, explicit transaction boundaries and one upgrade owner before worker startup. Rebuild tables where additive ALTER cannot remove constraints; explicitly replace derived views/triggers. Keep migrations independent from provider clients.

Alternative: Alembic, with its dependency and integration overhead. Both can work; current code has no ORM. The stdlib approach minimizes new dependencies but requires deliberate locking, checksum/ordering rules and upgrade-fixture coverage. Do not introduce a generic auto-repair that silently deletes or rewrites history.

Before application: choose mechanism, back up, build representative fixtures including inline inbound UNIQUE, old FTS view, sent/uncertain multipart runs and active extraction revisions. Rehearse interrupted upgrade and rollback/recovery on copies. Prefer roll-forward plus restore over claiming every destructive migration can be reversed. This proposal must not be mistaken for a completed migration system.

## ADR-002 — One VM, private workspace, isolated public ingress

Status: **topology required by roadmap; provider, region and access choice OPEN**.

Keep one persistent Linux VM with local disk, Compose or equivalent supervisor, separate private API, processing/scheduler and Instagram reply processes. Do not duplicate scheduler ownership across replicas. Telegram intake later uses one durable long-poll consumer. Expose only bounded webhook routes at stable HTTPS; retain explicit ownership for all private APIs and channel adapters.

Choices requiring owner input: WireGuard VPN versus identity-aware gateway for the workspace; VM provider/region and final capacity. WireGuard avoids per-user gateway dependency but requires device enrollment/key recovery. A gateway eases browser access but needs identity/session/CSRF and provider-specific configuration. Localhost development/Quick Tunnel is not the production access decision. No public API or UI exposure is approved.

Candidate costs and citations are in the baseline report; selected hosting, taxes, backups, disk and exchange-rate total are unapproved. Measure embedding memory in M4 before assuming 4 GB is sufficient. M1 can prepare local migration fixtures without purchasing a VM, but cannot claim deployed/restore acceptance without the approved target and actual drill.

## ADR-003 — Encrypted off-host backups and restoration

Status: **required behavior; destination, retention and key custodian OPEN**.

Proposed implementation for review: SQLite online backup API to a consistent snapshot, client-side authenticated encryption, independent off-host object storage, with encryption recovery material outside the VM. Exclude provider secrets from ordinary application-data archives; restore secrets separately. Restore first into an isolated environment with all deliveries disabled, validate saves/actions/index rebuilds and send-history/uncertainty preservation before promotion.

Proposed retention for owner approval: hourly snapshots for 48 hours, daily for 30 days, weekly for 12 weeks. These are proposals, not current guarantees. Roadmap RPO <=1h / RTO <=2h must be demonstrated. A same-host disk copy alone fails the off-host recovery requirement.

Destination choices: existing owner storage versus a new object-storage account (e.g. B2) with reviewed region/credentials/charges. Provider account, geographic storage preference, retention approval and encryption-key recovery location are missing. No bucket, credentials, cron job, backup or restoration was created. Do not decide a storage region or spend money on the user's behalf.

## ADR-004 — Zero paid model usage and ledger boundaries

Status: **zero paid inference is already a roadmap constraint; gateway design proposed for M3**.

Saving, browsing, notes, lexical retrieval, ranking and formatting must work without Gemini. Keep no automatic paid fallback. Do not treat the existing free-tier confirmation flag or local defaults as proof of billing status or current account quota. Verify the selected model/project dashboard and unpaid-data terms before live processing of personal content.

Recommend one gateway for Ask, single extraction, HTTP batches and fallback, with separate durable HTTP/token reservations and attempt records, actual project/model quota scope, Pacific RPD boundary, conservative ambiguous usage and explicit deferred/blocked recovery. Local limits can be stricter than the provider. No model rotation to bypass limits. Uploaded-video processing remains optional and excluded from default processing capacity.

No live account quota, billing setting or privacy consent was inspected during M0. Those are external facts requiring owner dashboard verification; they do not prevent documenting the source-level quota defects now.

## Approval boundary

The audit asked the owner for private-access and backup-destination preferences. Unanswered questions stay OPEN; silence does not choose an option. No irreversible later-work choice was made. Review these proposals with M0. Before M1 starts, record explicit approval to proceed and either resolve deployment/backup choices or scope M1's first work package to local migration/upgrade evidence while leaving its deployment exit gate open.
