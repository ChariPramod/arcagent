# Staging deployment and verification

This is an isolated staging recipe, not a deployed environment or proof of live vendor reliability. Use only invented caller details and owner-controlled phone numbers. Do not import production enquiry records. There are no new Python dependencies. The image installs the existing agent extras. Python dependency ranges remain unlocked; record the built image digest and installed package manifest before comparing releases. Pin a reviewed dependency lock and base image digest before production promotion.

## Prepare

Copy `deploy/.env.staging.example` to `deploy/.env.staging`. The destination is ignored by git. Fill it through your secret manager or editor, never in command history. Generate independent random admin and console credentials, each at least 32 characters. Set a separate database password and URL-encode it in `STAGING_DATABASE_URL`. Use hostname `postgres` and database `arcagent_staging` in that URL. Use dedicated staging vendor credentials and an owner-controlled coordinator destination. Do not reuse production credentials or numbers.

`ENV=prod` in the recipe enables production security rules; the infrastructure and data are nevertheless staging. Signature validation is enabled. Echo and audio-eval ingress are disabled. PostgreSQL has no host port. The backend binds only to loopback. Use an authenticated HTTPS ingress on your chosen platform with WebSocket support, an appropriate idle timeout, and the exact public origin in `PUBLIC_URL`. The recipe does not provision that ingress or certificate. Restrict the console/admin surface to trusted server traffic. The native Next.js frontend still needs a verified identity adapter before live workspace access.

Approve the prompt bundle and set its version. Existing unfinished prompts deliberately block voice readiness. Do not weaken the readiness check to make deployment appear successful.

## Build and migrate explicitly

From the repository root:

```sh
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yml build backend
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yml up -d postgres
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yml run --rm backend alembic upgrade head
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yml up -d backend
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yml exec backend python -m scripts.verify_staging --base-url http://127.0.0.1:8000
```

The verifier makes bounded local HTTP requests and reads the schema revision. It does not migrate, place calls, send messages, or probe vendor APIs. A failed gate exits nonzero and avoids printing credential-bearing exceptions. Redirects are refused. Missing/weak/shared credentials block before network access. `/health` is liveness only. Operations readiness checks configuration plus database access; vendor connectivity stays unknown even when the gate passes. Run the verifier from the matching release image, where `alembic.ini` and migrations are present.

Do not print expanded `docker compose config` output into CI logs because it includes secrets. Build contexts exclude environment files and unrelated workspace contents. The backend runs as an unprivileged user on a read-only filesystem, with one worker because coordination state is currently process-local. Container restart policies do not guarantee recovery of an active call.

## Controlled call acceptance

After the local gate passes, configure the staging number's inbound webhook to the staging HTTPS `/voice/inbound` endpoint using the provider dashboard. Use a consenting tester and synthetic details. Keep a coordinator available on the staging destination. Real calls and vendor usage may cost money; this runbook does not initiate them.

Record release/image digest, prompt version, scenario identity, approximate test time, and call ID. Verify qualification fields, deterministic routing decision, completed handoff or callback, and persisted final outcome. Known blocker: accepted transfer requests are currently recorded as handoffs without a verified answered/no-answer result handler. Automatic unanswered-transfer recovery is not implemented. Confirm this limitation with the controlled test, create a manual follow-up when needed, and do not promote to real callers until signed transfer-result handling and idempotent fallback have been implemented and tested. For callbacks, verify consent and SMS outcome independently. Inspect the Operations checks and call details. Confirm that latency sample coverage is explicit and missing measurements remain unknown. Playback acknowledgement is not audible-onset latency; do not add the stage columns into an end-to-end total.

Repeat with silence, interruption, caller disconnect, unavailable coordinator, and a deliberately unavailable vendor in the isolated staging environment. Never deliberately interrupt a real customer's call. Use the local deterministic failure lab first, and record separately which results are simulated versus observed with live audio.

## Backup and restore rehearsal

Before every migration of an environment that contains data, stop new test-call intake and wait for active calls to finish. Capture a PostgreSQL custom-format dump to an access-controlled location outside git:

```sh
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yml exec -T postgres pg_dump -U arcagent -d arcagent_staging -Fc > /secure/operator-chosen/staging.dump
```

Replace the output path with an existing protected directory. Treat dumps as sensitive even when staging should contain only synthetic data. Encrypt backups, restrict readers, and set retention. Restore the dump into a separately provisioned empty scratch database using `pg_restore --exit-on-error --no-owner`; never restore over the running staging database merely to test backups. Set the scratch database connection through a separate secret file, run the same image's migration revision check and console read smoke tests, and compare expected synthetic call counts and outcomes. A successful dump command alone is not a restore test. Delete the scratch environment and dump according to the retention policy after recording evidence.

## Failure and rollback procedure

For database outage, the Operations endpoint should report unavailable data without fabricated zeros; call/queue reads should show actionable failures. Restore database access, rerun the gate, and explicitly review incomplete calls. Do not automatically replay transfers, SMS, or callbacks after a restart because their external completion may be uncertain.

For a failing release, stop new intake, preserve evidence without transcript logging, and route the staging number to an owner-controlled fallback while repairing. Restart the pinned previous image only when its schema is compatible. Do not blindly run Alembic downgrade: inspect migration reversibility first and use the tested restore procedure if needed. Restart tests must demonstrate fresh-call acceptance, correct authentication, and persisted existing records after recovery. A mid-call restart can drop that call; keep this limitation visible until durable orchestration exists.

## Promotion evidence still required

A deployment owner must supply the isolated infrastructure, HTTPS ingress, credentials, approved prompts, identity integration, budget limits, backup location, and retention policy. Capture successful controlled-call traces and measured latency distributions. Exercise recovery and restore on the target platform. Load-test expected concurrency with synthetic traffic before increasing worker count or routing customer traffic. This repository does not make the system break-proof, and a passing local suite cannot establish live operational readiness.

CI builds the staging image and checks packaged application imports plus migrations using an ephemeral SQLite database in a read-only container. This packaging smoke test does not validate PostgreSQL operation, Compose networking, HTTPS ingress, or live vendors.
