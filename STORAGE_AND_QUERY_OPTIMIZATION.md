# Storage and query optimization

This change makes transcript retention safe to preview and bounded to apply, preserves call and delivery evidence, and exposes a read-only data-health view. Query improvements and verification evidence are recorded below. These are implementation limits and checks, not measured production latency or storage savings.

## Transcript retention

The earlier script selected every old call ID into application memory and deleted whole turn rows. That also removed latency and interruption evidence. It now clears only nonempty `Turn.text`, records `Turn.transcript_redacted_at`, and retains the turn row.

A turn qualifies only when its call has a non-null `ended_at` strictly earlier than the configured retention cutoff, its text is nonempty, and it has not already been marked as redacted. The default retention window remains 30 days. The cutoff now uses call completion time instead of call start time. Active calls, calls without confirmed completion, and calls ending exactly at the cutoff do not qualify.

The routine preserves:

- Turn IDs, speaker, timestamps, latency measurements, interruption flags and graph node labels.
- Calls, leads, callbacks, consent evidence, scores and operator pipeline state.
- Workflow and location audits, including their existing content.
- CRM delivery snapshots, delivery outcomes and idempotency keys.
- Evaluation runs and their evidence.

This routine is not a full personal-data erasure workflow. Extracted fields, staff notes, audit content, evaluation transcripts, CRM snapshots, backups and vendor-held data require their own approved retention policy. A call left unfinished after a crash needs outcome reconciliation before it can become eligible; the script never guesses that an old open call has ended.

## Preview and apply

Use an environment containing the intended `DATABASE_URL`. Preview is now the default:

```bash
python -m scripts.purge_old_data
python -m scripts.purge_old_data --dry-run --days 30 --batch-size 500 --max-batches 10
```

After reviewing the preview and confirming the applicable retention policy, an operator can explicitly apply it:

```bash
python -m scripts.purge_old_data --apply --days 30 --batch-size 500 --max-batches 10
```

No apply operation was run against staging or production while implementing this change. The website exposes no retention write endpoint.

The default invocation considers at most 5,000 eligible turns, in batches of 500. The accepted bounds are 1 to 1,000 turns per batch and 1 to 100 batches. Retention days must be between 1 and 36,500. These explicit limits bound application memory and the amount of work attempted in one invocation. PostgreSQL additionally has transaction-local statement and lock timeouts of 3 seconds and 1 second. SQLite tests do not use those PostgreSQL settings.

Each apply batch commits independently. If a later batch fails, earlier batches may already have succeeded. The script reports failure without printing database details. Rerunning is safe because redacted turns no longer qualify. A write rechecks eligibility and counts only rows it changed, so overlapping retention workers do not count the same redaction twice. The final `has_more` flag indicates whether eligible content remains; batch completion does not imply the entire database has been processed.

The job is still manually invoked. Scheduling, missed-run alerts and a service identity dedicated to retention are deployment work. Do not schedule an applying job until the owner has approved the retention policy and tested its operational handling.

## Data-health endpoint

`GET /api/console/storage?limit=1000` uses the same console bearer authentication and no-store response policy as other workspace reads. Authentication runs before database work. The limit is between 1 and 1,000 candidate turns.

The endpoint returns a bounded preview of eligible turn and call counts, the total text-character count within that preview, the retention cutoff, and `has_more`. It retrieves identifiers and text lengths; it never sends transcripts, caller identities, database credentials or CRM payloads to the browser. The preview query asks for one additional row to detect truncation.

When `has_more` is true, the displayed counts are lower bounds for the backlog. Character count is the amount of plaintext in the preview, not bytes allocated by PostgreSQL, backup size, billable storage or space reclaimed. `physical_storage_bytes` is deliberately null. A database error or statement timeout returns `database.available: false` and `retention: null`, rather than an apparently empty backlog.

## Verification

The focused retention and storage API suite passed 24 tests during implementation. It covers dry-run default, explicit apply, cutoff and argument validation, active-call exclusion, bounded resumable batches, retained latency and business/delivery/audit evidence, safe repeat application, failure after a committed batch, sanitized CLI failure, authentication before database access, truncated previews, no payload disclosure and unavailable-versus-empty responses.

There are no new runtime dependencies. The schema change adds a nullable timestamp marker and is included in the shared query migration. Existing turns start without a marker; they are not treated as already redacted.

## Query behavior and new staff queues

`GET /api/console/pipeline` now accepts `due=overdue`, `due=scheduled`, or `due=unscheduled`, and `owner=unassigned`. Due queues contain open conversion stages only: `new`, `contacted`, and `booked`. Overdue means a saved next-action timestamp strictly before a UTC instant captured once for the request; scheduled means at or after that instant. Unscheduled means no next-action timestamp, including enquiries without a saved workflow. Closed outcomes are excluded from due queues.

`owner=unassigned` includes null and space-only historical assignees. This is independent of the existing `unassigned=true` location filter. Location, due and owner filters scope both the page and the stage-summary counts. The optional `stage` filter then narrows `items` and `total`, while `summary` retains the other stage counts for that work queue. Pagination does not change the summary. Filtering uses stored timestamps; no client timezone is inferred by the backend.

Pipeline page queries project only the required call, contact and workflow fields. The count query uses lead existence, so it does not load contact rows, sort all historical leads or join location names. Each call's displayed contact is its latest saved lead by ID. Pipeline audit existence checks also query an ID rather than loading the entire enquiry.

Call lists now select a single latest lead and score through indexed correlated lookups. They no longer load every score object or contact medical fields to render each card. Call detail uses the same latest-record rule; detail responses continue to include the requested saved transcript and score breakdown.

Evaluation lists aggregate repetitions into per-scenario scalar statistics in SQL. They do not retrieve expected/actual JSON, transcripts, notes or full persona snapshots for a summary card. Detail and comparison endpoints continue to retrieve their necessary evidence. Floating-point averages use SQL sums and counts for the list, so harmless last-bit rounding differences from the detailed Python calculation are possible.

## Schema and index changes

Migration `g05cf124de67`, following `f94be013cd56`, adds the nullable transcript-redaction marker and these indexes:

| Index | Purpose |
| --- | --- |
| `calls(started_at, id)` | Stable recent-call pagination |
| `calls(outcome, started_at, id)` | Outcome-filtered recent-call pagination |
| `leads(call_id, id)` | Latest captured contact and lead-existence lookup |
| `lead_scores(lead_id, id)` | Latest score lookup |
| `turns(id) WHERE transcript_redacted_at IS NULL` | Skip already-redacted history while scanning a retention batch |

The lead and score composites replace their single-column foreign-key-prefix indexes, preserving those prefix lookups without retaining redundant index copies. The pending-transcript partial index uses only `IS NULL`, so it does not depend on PostgreSQL proving a parameterized text predicate. Empty unmarked turns can remain in that index, and recent pending turns can still require scanning before an eligible old call is found.

The migration uses ordinary index creation suitable for the current small staging database. On a large active deployment, plan index creation with PostgreSQL's concurrent-index procedure and migration transaction handling before running it. Apply migrations before deploying code that selects the new marker. Do not downgrade after relying on redaction evidence: dropping its marker cannot restore cleared text and would remove the record of that redaction time.

## Reproducible local query evidence

Run `.venv/bin/python -m scripts.profile_console_queries` from the repository root. The script creates and removes a temporary synthetic SQLite database; it never connects to staging or vendors. Its fixture contains 1,000 calls, 5 scores per call and 300 evaluation results with deliberately bulky synthetic JSON/text.

The observed call page used 4 SELECTs under the former ORM loading shape, including its count, and 2 SELECTs under the new projection, also including its count. The overdue pipeline page and summary used 2 SELECTs. Evaluation summaries used 3 SELECTs, with repeated scenarios grouped in the database. Public-route tests additionally assert that call cards do not select objections/score-breakdown payloads, and evaluation cards do not select transcript/expected/actual payloads.

SQLite `EXPLAIN QUERY PLAN` selected `ix_calls_started_id` for call ordering, covering composite indexes for latest lead/score lookup, and the existing evaluation run-ID index for scalar aggregation. Retention selected `ix_turns_pending_transcript_id (id>?)` and a call primary-key lookup. Removing that partial index changed retention to scanning the turn primary-key range. An experimental `calls(ended_at,id)` index did not improve that retention plan, so it is not included in the migration. The experiment is only created inside the temporary profiling database.

These are query-shape and local planner observations, not measured PostgreSQL latency, billing reduction or physical space reclaimed. Exact totals still scan the relevant rows, offset pagination becomes more expensive at large offsets, and sparse retention eligibility can require scanning many pending turns despite a bounded returned batch. Production-sized PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` evidence and cursor pagination are follow-up work when representative volumes are available.
