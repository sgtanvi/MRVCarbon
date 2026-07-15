# mrvcarbon infra plan: real queue, real cache, real batch job

## Why

We're past the hackathon and moving toward real, unattended deployment. Right now the "store-and-forward" in `edge/audit.py` / `edge/main.py` is a `synced` boolean column plus a 30s poll loop, and `cloud/main.py`'s `_build_note()` recomputes every report from scratch on every request — there's no queue, no cache, no batch layer. That was fine for a demo, but two concrete problems follow directly from it once this runs unattended for real: (1) `/sync` double-inserts on a lost-response retry, corrupting the audit trail cloud-side, and (2) `_build_note()` re-scans and re-renders every closed, immutable day on every single request, which gets slower and more wasteful the longer the deployment runs.

Note: this is *not* a prerequisite for the README's listed gaps (regulatory export, multi-site federation) — those are independent and don't depend on this infra existing first. This plan is justified on its own: fixing a real correctness bug (A) and real wasted work (B/C), nothing more.

This plan adds three pieces, in dependency order, each solving a real problem already latent in the code — not infra for its own sake.

## Scope decision: no Redis/Kafka/Celery

The topology is one edge device and one cloud service. A message broker is built for many producers/consumers coordinating across a network; here it's one producer, one consumer, using SQLite already. The "SQLite as a queue" pattern is explicitly recommended for exactly this shape of problem — low/medium frequency, single-writer, needs persistence and inspectability, not infrastructure ([dev.to/hexshift](https://dev.to/hexshift/build-a-shared-nothing-distributed-queue-with-sqlite-and-python-3p1), [litequeue](https://github.com/litements/litequeue)). Pulling in Redis or RabbitMQ would contradict the project's own "offline-first, no external DB" design goal in the README. So: same storage engine, better pattern.

---

## Part A — Durable outbound queue + idempotent consumer for edge→cloud sync

(Not a textbook transactional outbox — that pattern separates business-state writes from an events-to-publish table written in the same transaction. Here `decisions` *is* the business data; it's functioning as a durable send queue. Same shape of problem, different name, no design change.)

**Problem this actually fixes:** `cloud/main.py` `/sync` (line 185) inserts every row in the payload unconditionally. If the edge POSTs a batch, the cloud commits it, but the HTTP response is lost before the edge sees `200` — the edge retries the same batch next cycle and the cloud double-inserts. There's also no backoff or dead-letter path: a row that fails forever just gets silently retried every 30s indefinitely, and `/status`'s `unsynced_decisions` count doesn't distinguish "just written" from "stuck for 3 days."

This is the exact dual-write problem the transactional outbox pattern addresses: write the event and the business state in one local transaction, let a separate relay push it, and require the consumer to dedupe ([microservices.io/patterns/data/transactional-outbox](https://microservices.io/patterns/data/transactional-outbox.html), [AWS Prescriptive Guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)). The pattern gives **at-least-once delivery**, which is only safe if the consumer is idempotent — that's the "Inbox"/idempotent-consumer half of the pattern ([bool.dev](https://bool.dev/blog/detail/inbox-and-outbox-patterns)).

**Design:**
- `edge/audit.py`: `decisions` table already *is* the queue (this part is already correctly designed — keep it). Add columns: `sync_attempts INTEGER DEFAULT 0`, `last_sync_attempt_at TEXT`, `last_sync_error TEXT`, `next_retry_at TEXT`.
- `edge/main.py` `sync_loop()` (line 78): on failed POST or non-200, increment `sync_attempts`, record the error, and set `next_retry_at` to `now + min(30s * 2^sync_attempts, 3600s)` — exponential backoff capped at 1 hour, not a fixed retry count. `sync_loop` skips rows whose `next_retry_at` hasn't passed yet. Transient failures (connection refused, timeout, 5xx) retry forever with backoff; only a permanent failure the cloud can identify (malformed payload, schema mismatch — a 4xx the cloud returns deliberately) marks a row `sync_status='dead_letter'`. Reasoning: a fixed retry-count threshold would dead-letter the entire backlog after a routine multi-hour cloud restart, turning a non-event into a manual-replay incident — backoff keeps retrying automatically once the cloud is back.
- `cloud/main.py`: add a `UNIQUE(edge_id, edge_decision_id)` constraint on the `decisions` table and change the insert to `INSERT OR IGNORE`. This makes replayed/duplicate batches safe — the idempotent-consumer half of the pattern. `synced_ids` in the response already tells the edge what the cloud has, so re-marking synced after a dedup is a no-op.
- Enable WAL mode on the cloud SQLite connection (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`) so concurrent `/sync` writes under FastAPI's async concurrency don't hit `database is locked` errors.
- All timestamps (`last_sync_attempt_at`, `next_retry_at`, rollup `date_str` bucketing) are strict UTC ISO 8601 — edge clock drift/timezone offsets must not be allowed to bucket a decision into the wrong day.
- Extend `/status` (edge) with `dead_letter_count`, `oldest_unsynced_age_s`, `sync_success_total`, `sync_failure_total` — cheap counters since `sync_loop` already touches this path on every attempt; a fuller metrics surface (rollup duration, cache hit rate, per-batch dedup counts) belongs to the ops CLI pass in Sequencing step 4, not here.

**New dependency:** none — same `aiosqlite`/`httpx` already in `edge/requirements.txt` and `cloud/requirements.txt`.

### Priority within the outbox — considered, deliberately not doing it now

Plain FIFO (`ORDER BY id`) does mean that if a sync backlog builds up, routine "normal ops" rows queue ahead of `OMEGA_BELOW_SAFETY_THRESHOLD` / `PLAUSIBILITY_FAIL` / `HOLD` rows an auditor would most want to see first. That's a real theoretical gap, but for a single edge device with a 30s sync cadence, the backlog scenario that would make it matter (a multi-hour+ cloud outage) hasn't happened yet, and building a tiered-priority query plus aging (to avoid starving normal rows) is real complexity — a second sort key, a time-based override, more surface for the reconciliation risk noted below — for a problem we haven't observed.

Not building this now. If a real deployment produces backlogs long enough that ordering starts to matter (visible via the `dead_letter_count` / `oldest_unsynced_age_s` fields Part A adds to `/status`), revisit then with real backlog data instead of guessing at tiers and thresholds up front.

---

## Part B/C — Materialized daily rollups + cache-aside for "today"

These two are really one problem viewed at two timescales, so building them together avoids duplicating the aggregation logic.

**Problem this actually fixes:** `_build_note()` in `cloud/main.py` (line 256) re-scans the `decisions` table and recomputes medians, reason-code histograms, and HTML on *every single call* to `/mrv_note` and `/export` — including for days that are closed and will never change again. In a real deployment this table only grows, so the wasted work grows too; today it's a demo-scale non-issue, in production it's a recompute cost that never amortizes.

The right split, per the caching-pattern literature: closed/past days are immutable, so they're a good fit for **precomputed materialized aggregates** — computed once, read many times, staleness is explicit and bounded by when the job last ran ([Azure Cache-Aside](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside), [Stormatics on materialized views](https://stormatics.tech/blogs/postgresql-materialized-views-when-caching-your-query-results-makes-sense)). Today's data is still arriving, so it's a better fit for **cache-aside with a short TTL** — reactive, on-demand, bounded staleness measured in seconds not hours.

**Design:**

*Batch job (Part C):*
- New table `daily_rollups` in `cloud`'s SQLite: `date_str PK, edge_id, n_decisions, avg_confidence, median_cap_low/mid/high, min_omega, max_omega, pct_time_hold, reason_code_histogram_json, chain_verified, computed_at, last_decision_id, invalidated_at`.
- New module `cloud/rollup.py` with a `compute_rollup(date_str)` function — pulls the same aggregation `_build_note()` already does, plus new stats (% time in HOLD, longest hold streak) not currently computed anywhere.
- Runs as a background `asyncio` loop in `cloud/main.py`'s `lifespan()`, same style as `decision_loop`/`sync_loop` already in `edge/main.py` — no new scheduler dependency; assumes a single FastAPI/uvicorn process (true today — `cloud/Dockerfile` runs `uvicorn` with no `--workers`; if that ever changes to multiple workers, this loop needs a leader-election or external-scheduler guard to avoid running N times). Wakes hourly, rolls up any day that's closed (UTC date < today) and has no rollup yet, or whose stored `last_decision_id` is behind `MAX(id)` for that day's rows (handles a late sync landing after the day was already rolled up). `MAX(id)` is used instead of a raw row count: `decisions` is insert-only today (checked — cloud never issues `UPDATE decisions`), so either watermark works for that case, but `MAX(id)` is also immune to the count going *down*, which the dedup migration in Part A's non-goals section could otherwise cause. The per-day aggregation query should read via short-lived transactions/batched selects rather than one long-held read, so it doesn't block concurrent `/sync` writes for the duration of the scan.
- Also exposed as `POST /rollup/run?date_str=` for manual backfill, so the ops CLI or a person can force a recompute.
- `chain_verified` per day requires slicing the existing `/verify_chain` logic (`cloud/main.py` line 348) to a contiguous ID range rather than the whole table, since the hash chain runs across day boundaries.

*Cache-aside (Part B):*
- `_build_note()` becomes: if `date_str` has a fresh `daily_rollups` row (`invalidated_at IS NULL`) → build HTML from the rollup (fast path, no raw-row scan). If `date_str` is today, has no rollup yet, or its rollup is invalidated → compute from raw rows as it does now, but cache the *rendered HTML* in-memory for a short TTL (e.g. 60s) so rapid repeat requests (dashboard polling, someone hammering Export) don't each trigger a full recompute. In-memory cache key is `date_str` alone — there's exactly one `edge_id` in this deployment, so keying on `(edge_id, date_str)` would add a dimension with zero current variance; revisit only if multi-site actually gets built.
- Invalidate-on-write: `/sync` already knows which `date_str` buckets it just inserted into — clear that date's TTL cache entry, and set `invalidated_at` (not delete) on a stale `daily_rollups` row for that date, on write, rather than relying on TTL expiry alone. Marking stale instead of deleting preserves `computed_at`/`chain_verified`/prior stats for debugging until the rollup job recomputes it. This is the standard cache-aside gap-filler: TTL bounds staleness, invalidation handles the common case immediately. The raw-row insert and the rollup invalidation must happen in the same SQL transaction — if the insert commits but the invalidation update fails, the rollup silently stays "fresh" and serves stale data with no signal that it happened.
- No Redis needed — single FastAPI process, in-memory dict is sufficient and simplest; SQLite would only be worth it if the cache needed to survive a container restart, which for a 60s TTL it doesn't.

**New dependency:** none.

---

## Sequencing

1. **Part A first.** If duplicate rows can land in `cloud`'s `decisions` table, any aggregation built on top of it (rollups, cache) inherits the bug. Fixing idempotency is a prerequisite, not parallel work.
2. **Part C next** (rollup table + batch job) — this is the real deliverable; it also *is* the cache for closed days.
3. **Part B last** (thin TTL cache for today) — small, and only meaningful once C exists to show the contrast between "closed day, served from rollup" and "today, served from short-lived cache."
4. **Then** extend the ops CLI discussed earlier to report on this real infra: dead-letter count and oldest-unsynced age (A), rollup freshness/last-run (C), cache hit rate (B), per-day chain verification (C). At that point the observability layer is watching something that actually exists, instead of two bare `/health` endpoints.

## Explicit non-goals / risks

- Not introducing a real message broker or Celery — would be over-engineering for one edge + one cloud, and contradicts the project's offline-first design goal.
- Not building priority/aging into the queue now — see the note under Part A; revisit only if real backlog data shows it's needed.
- Not keying the daily-note cache or rollups by `edge_id` now — this deployment has exactly one edge; adding a federation-shaped key for a topology that doesn't exist yet is the same speculative-complexity mistake this plan avoids elsewhere.
- Not building a full metrics suite now — `/status` gets the counters cheap to add alongside Parts A/B (dead-letter count, unsynced age, sync success/failure, cache hit/miss); anything heavier (rollup duration, per-batch dedup counts) is scoped to the ops CLI pass in Sequencing step 4.
- Rollup table is a second source of truth that must stay reconciled with raw `decisions` — handled by the "recompute if raw count grew" check above, but worth calling out as the main correctness risk in this plan.
- `UNIQUE(edge_id, edge_decision_id)` is a schema migration on `cloud`'s existing `decisions` table. Current `cloud_audit.db` has 57,094 rows and zero existing duplicates on that pair (checked directly), so this is low-risk, but the migration must still run as: (1) idempotent dedup delete keeping `MIN(id)` per `(edge_id, edge_decision_id)`, in case that ever changes, then (2) `CREATE UNIQUE INDEX IF NOT EXISTS` — not a table rebuild, since SQLite can add a unique index without an `ALTER TABLE` copy-and-swap. Both steps run at startup, idempotently, not as a one-off script, so `docker compose up` keeps working from any state.

## Testing

Not covered above but required before calling any part done, since this is going into real unattended deployment:
- Part A: a test that replays the same `/sync` batch twice and asserts no duplicate rows land in `cloud`'s `decisions` table.
- Part A: a test that a transient failure (simulated connection error) backs off and keeps retrying, while a simulated permanent failure (malformed payload) dead-letters immediately without retrying.
- Part C: a test for the `last_decision_id` watermark reconciliation path — the main correctness risk called out above — using a late-arriving sync into an already-rolled-up day, asserting the rollup recomputes and `invalidated_at` clears.

## Sources

- [Microservices.io — Transactional Outbox pattern](https://microservices.io/patterns/data/transactional-outbox.html)
- [AWS Prescriptive Guidance — Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- [bool.dev — Transactional Inbox and Outbox Patterns](https://bool.dev/blog/detail/inbox-and-outbox-patterns)
- [dev.to — Build a Shared-Nothing Distributed Queue with SQLite and Python](https://dev.to/hexshift/build-a-shared-nothing-distributed-queue-with-sqlite-and-python-3p1)
- [litequeue — SQLite-backed queue (GitHub)](https://github.com/litements/litequeue)
- [dev.to — Why I Built a Job Queue With SQLite Instead of Redis](https://dev.to/d_security/why-i-built-a-job-queue-with-sqlite-instead-of-redis-and-what-i-learned-4f05)
- [Microsoft Learn — Azure IoT Edge offline capabilities](https://learn.microsoft.com/en-us/azure/iot-edge/offline-capabilities) (store-and-forward reference design)
- [Azure Architecture Center — Cache-Aside pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)
- [Stormatics — PostgreSQL Materialized Views: when caching query results makes sense](https://stormatics.tech/blogs/postgresql-materialized-views-when-caching-your-query-results-makes-sense)
- [ml4devs — Data Pipeline: Batch, Streaming, and Idempotent Patterns](https://www.ml4devs.com/what-is/data-pipeline/)
