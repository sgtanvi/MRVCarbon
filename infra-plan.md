# mrvcarbon infra plan: real queue, real cache, real batch job

## Why

We're past the hackathon and moving toward real, unattended deployment. Right now the "store-and-forward" in `edge/audit.py` / `edge/main.py` is a `synced` boolean column plus a 30s poll loop, and `cloud/main.py`'s `_build_note()` recomputes every report from scratch on every request — there's no queue, no cache, no batch layer. That was fine for a demo, but two concrete problems follow directly from it once this runs unattended for real: (1) `/sync` double-inserts on a lost-response retry, corrupting the audit trail cloud-side, and (2) `_build_note()` re-scans and re-renders every closed, immutable day on every single request, which gets slower and more wasteful the longer the deployment runs.

Note: this is *not* a prerequisite for the README's listed gaps (regulatory export, multi-site federation) — those are independent and don't depend on this infra existing first. This plan is justified on its own: fixing a real correctness bug (A) and real wasted work (B/C), nothing more.

This plan adds three pieces, in dependency order, each solving a real problem already latent in the code — not infra for its own sake.

## Scope decision: no Redis/Kafka/Celery

The topology is one edge device and one cloud service. A message broker is built for many producers/consumers coordinating across a network; here it's one producer, one consumer, using SQLite already. The "SQLite as a queue" pattern is explicitly recommended for exactly this shape of problem — low/medium frequency, single-writer, needs persistence and inspectability, not infrastructure ([dev.to/hexshift](https://dev.to/hexshift/build-a-shared-nothing-distributed-queue-with-sqlite-and-python-3p1), [litequeue](https://github.com/litements/litequeue)). Pulling in Redis or RabbitMQ would contradict the project's own "offline-first, no external DB" design goal in the README. So: same storage engine, better pattern.

---

## Part A — Outbox pattern + idempotent consumer for edge→cloud sync

**Problem this actually fixes:** `cloud/main.py` `/sync` (line 185) inserts every row in the payload unconditionally. If the edge POSTs a batch, the cloud commits it, but the HTTP response is lost before the edge sees `200` — the edge retries the same batch next cycle and the cloud double-inserts. There's also no backoff or dead-letter path: a row that fails forever just gets silently retried every 30s indefinitely, and `/status`'s `unsynced_decisions` count doesn't distinguish "just written" from "stuck for 3 days."

This is the exact dual-write problem the transactional outbox pattern addresses: write the event and the business state in one local transaction, let a separate relay push it, and require the consumer to dedupe ([microservices.io/patterns/data/transactional-outbox](https://microservices.io/patterns/data/transactional-outbox.html), [AWS Prescriptive Guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)). The pattern gives **at-least-once delivery**, which is only safe if the consumer is idempotent — that's the "Inbox"/idempotent-consumer half of the pattern ([bool.dev](https://bool.dev/blog/detail/inbox-and-outbox-patterns)).

**Design:**
- `edge/audit.py`: `decisions` table already *is* the outbox (this part is already correctly designed — keep it). Add columns: `sync_attempts INTEGER DEFAULT 0`, `last_sync_attempt_at TEXT`, `last_sync_error TEXT`.
- `edge/main.py` `sync_loop()` (line 78): on failed POST or non-200, increment `sync_attempts` and record the error instead of silently looping. After a configurable threshold (e.g. 10 attempts), mark the row `sync_status='dead_letter'` and stop retrying it automatically — surfaced via `/status` so it's visible instead of retrying forever unnoticed.
- `cloud/main.py`: add a `UNIQUE(edge_id, edge_decision_id)` constraint on the `decisions` table and change the insert to `INSERT OR IGNORE`. This makes replayed/duplicate batches safe — the idempotent-consumer half of the pattern. `synced_ids` in the response already tells the edge what the cloud has, so re-marking synced after a dedup is a no-op.
- Extend `/status` (edge) with `dead_letter_count` and `oldest_unsynced_age_s`, so the observability layer built earlier has something real to watch.

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
- New table `daily_rollups` in `cloud`'s SQLite: `date_str PK, edge_id, n_decisions, avg_confidence, median_cap_low/mid/high, min_omega, max_omega, pct_time_hold, reason_code_histogram_json, chain_verified, computed_at`.
- New module `cloud/rollup.py` with a `compute_rollup(date_str)` function — pulls the same aggregation `_build_note()` already does, plus new stats (% time in HOLD, longest hold streak) not currently computed anywhere.
- Runs as a background `asyncio` loop in `cloud/main.py`'s `lifespan()`, same style as `decision_loop`/`sync_loop` already in `edge/main.py` — no new scheduler dependency. Wakes hourly, rolls up any day that's closed (UTC date < today) and has no rollup yet, or whose raw row count has grown since its last rollup (handles a late sync landing after the day was already rolled up).
- Also exposed as `POST /rollup/run?date_str=` for manual backfill, so the ops CLI or a person can force a recompute.
- `chain_verified` per day requires slicing the existing `/verify_chain` logic (`cloud/main.py` line 348) to a contiguous ID range rather than the whole table, since the hash chain runs across day boundaries.

*Cache-aside (Part B):*
- `_build_note()` becomes: if `date_str` has a fresh `daily_rollups` row → build HTML from the rollup (fast path, no raw-row scan). If `date_str` is today or has no rollup yet → compute from raw rows as it does now, but cache the *rendered HTML* in-memory for a short TTL (e.g. 60s) so rapid repeat requests (dashboard polling, someone hammering Export) don't each trigger a full recompute.
- Invalidate-on-write: `/sync` already knows which `date_str` buckets it just inserted into — clear that date's cache entry (both the TTL cache and, if it exists, a stale `daily_rollups` row) on write, rather than relying on TTL expiry alone. This is the standard cache-aside gap-filler: TTL bounds staleness, invalidation handles the common case immediately.
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
- Not building priority/aging into the outbox queue now — see the note under Part A; revisit only if real backlog data shows it's needed.
- Rollup table is a second source of truth that must stay reconciled with raw `decisions` — handled by the "recompute if raw count grew" check above, but worth calling out as the main correctness risk in this plan.
- `UNIQUE(edge_id, edge_decision_id)` is a schema migration on `cloud`'s existing `decisions` table — needs a migration step (or safe `CREATE TABLE IF NOT EXISTS` + backfill) rather than a clean slate, since `cloud/data/cloud_audit.db` already has data in it.

## Testing

Not covered above but required before calling any part done, since this is going into real unattended deployment:
- Part A: a test that replays the same `/sync` batch twice and asserts no duplicate rows land in `cloud`'s `decisions` table.
- Part C: a test for the "recompute if raw row count grew since last rollup" reconciliation path — the main correctness risk called out above — using a late-arriving sync into an already-rolled-up day.

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
