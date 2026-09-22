# Cloud staging deployment plan

Status: isolated project `arcagent-staging-20260922` has been created and linked to the sole accessible open billing account. A project-scoped $15 monthly alerts budget is configured at 50%, 80%, and 100% thresholds. Required Cloud Run, Cloud SQL, Secret Manager, Artifact Registry, and Cloud Build APIs are enabled. The backend runtime is deployed and healthy. The small persistent PostgreSQL database is running and migrated. Authenticated operations, calls, and follow-up reads succeed against that database; voice readiness correctly remains false. The unrelated previously selected project is unchanged. Existing Vercel hosting remains the frontend target.

## Intended layout

Use a new isolated ArcAgent staging project, with Cloud Run and Cloud SQL PostgreSQL in the same US region. Keep the existing Python image and migrations. Cloud Run supports WebSockets, but connections remain subject to request timeouts and clients must handle disconnects. Do not store SQLite or uploads on the Cloud Run filesystem: instances are disposable. PostgreSQL holds calls, workflow records, and transfer recovery state. [Cloud Run WebSocket documentation](https://docs.cloud.google.com/run/docs/triggering/websockets).

Use one Python worker, zero minimum instances, one maximum instance, request-based CPU billing, a bounded request timeout, and explicit service concurrency suitable for a small controlled test. Zero minimum instances introduces cold starts. A maximum instance setting does not by itself make process-local state durable or impose a monetary cap. Never run migrations automatically on every application startup. Build once, migrate in a controlled one-off job, then deploy the same image digest.

The runtime service account needs only access to its specific Secret Manager secrets and Cloud SQL connection permission. Use the Cloud SQL integration and a Unix socket connection with the existing psycopg SQLAlchemy driver. Do not add public database authorized networks. Store the complete database URL as a secret and mount it through the platform's secret integration; never put passwords in deployment arguments, build arguments, image layers, or GitHub files.

## Budget envelope

The owner has authorized up to $20 per month for staging infrastructure. The following is a planning estimate for low usage, not a guaranteed invoice or authorization to exceed that ceiling. Verify the chosen region's prices immediately before provisioning.

| Component | Proposed configuration | Planning amount per month |
| --- | --- | --- |
| PostgreSQL compute | Cloud SQL Enterprise shared-core `db-f1-micro`, single zone, no replica | About $7.67 at the listed $0.0105/hour rate over 730 hours |
| PostgreSQL SSD | Minimum 10 GiB, storage auto-increase disabled for this bounded staging test | About $1.70 at $0.17/GiB-month; recheck region |
| Cloud Run | Request billing, minimum zero, maximum one; short controlled tests | Allocate $3, with a service spend-cap budget where available |
| Backups, image storage, build, secrets, logs, and networking | Small retention and build volume; no recordings | Reserve the remaining budget |

The shared-core database has limited memory and no Cloud SQL SLA. It is suitable for a small staging demonstration, not a production reliability commitment. Database backup retention and storage limits must be explicit; a full disk must fail visibly rather than silently expanding spending. [Cloud SQL pricing](https://cloud.google.com/sql/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing).

Set a project-wide alerts budget below the ceiling, with early alerts, and configure a separate Cloud Run spend-cap budget if supported by the billing account. Ordinary alerts do not stop spending. Cloud Run spend caps are currently preview functionality, are service-specific, may enforce after a delay, and do not stop persistent database or storage charges. Account for all services and taxes before launch. A strict no-overage guarantee is not established by this architecture. [Budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets), [spend-cap limitations](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps).

## Concrete activation sequence

1. Designate a new ArcAgent staging project and the accessible billing account. Do not reuse or modify an unrelated selected project just because the CLI is signed in.
2. Verify the final region-specific estimate and configure cost monitoring before creating persistent resources. If the estimate plus reserve cannot fit, stop before provisioning.
3. Enable only required APIs for build, artifact storage, Cloud Run, Cloud SQL, and secrets. Create a dedicated runtime service account and an image repository with explicit retention.
4. Create the small PostgreSQL instance, staging database, and least-privilege application user. Put its URL and independent random console/admin credentials into Secret Manager. Preserve the secret versions used by each release without printing values.
5. Build `deploy/Dockerfile` remotely because Docker is not installed in the current workspace. Use an explicit source manifest so environment files, local databases, dumps, and deployment credentials cannot enter the upload. Review that manifest before submitting.
6. Run Alembic against the staging database through a one-off job using the same image and secrets. Record the schema revision and image digest. Do not accept traffic if migration fails.
7. Deploy the service on container port 8000 with the Cloud SQL connection attached. Initially keep voice readiness blocked while vendor credentials and approved prompts are absent. Liveness does not imply voice readiness.
8. Set the verified service origin as `PUBLIC_URL`. Connect Vercel's server-only `ARCAGENT_API_URL` and matching `ARCAGENT_API_TOKEN`. Complete OIDC client registration and approved user identities before exposing real records. The browser must never receive the backend bearer credential.
9. Run `scripts.verify_staging`, test unauthorized console requests, verify authenticated reads and a synthetic workflow write, and exercise the database outage response. Record real cloud evidence separately from unit tests.
10. Perform backup and restore into a separate empty scratch target only when its cost is budgeted. Use the detailed migration, recovery, and controlled-call gates in [STAGING_RUNBOOK.md](STAGING_RUNBOOK.md). Delete scratch resources after verifying retained evidence.

## Inputs that still gate activation

The isolated project and billing link now exist. Automated spend-cap setup is not exposed by the installed CLI or current public Billing Budgets discovery schema; official instructions provide a Console setup flow. This is an outstanding cost-control step, not an implemented hard cap. No staging vendor credentials or phone destinations are configured in this workspace. Native website authentication additionally requires an OIDC issuer/client registration and approved stable user identities. These credentials should be entered through secret managers or provider dashboards, never chat.

A cloud workspace can be brought up without placing calls. A real call remains a separate acceptance test requiring approved prompts, controlled phone numbers, consent, vendor credentials, and an agreed usage allowance. Do not infer that the infrastructure budget includes unlimited telephony, transcription, model, or speech-synthesis charges.

## Prepared build configuration

`deploy/cloudbuild.yaml` builds the existing Dockerfile with a caller-supplied `_IMAGE` Artifact Registry path and a bounded build timeout. The root `.gcloudignore` explicitly allows application source, migrations, scripts, and required build files while excluding environment files, databases, dumps, and key material. `gcloud meta list-files-for-upload` was checked: 99 files, with no detected environment files, local databases, dumps, deployment credentials, or key files. Review this manifest again immediately before each submission because source changes can alter it. Both remote builds succeeded. The final build uses 100 source files and includes transfer evidence plus stale-attempt reconciliation.

## Deployed resource inventory

- Project: `arcagent-staging-20260922`, region `us-central1`.
- Backend: `https://arcagent-staging-ydan5h6udq-uc.a.run.app`.
- PostgreSQL instance: `arcagent-staging-db`; migrated by execution `arcagent-migrate-dtfcb`.
- Final build: `4a6eaf42-d67f-4b43-b7be-fe67bb5672e0`.
- Image digest: `sha256:a1c933328f4b3f903df56795dd96859a23d40943e044f3b07cbe65724a31f404`.
- Runtime application source matches commit `33529a9`; deployment documentation/configuration is recorded separately.
- Dedicated identities: `arcagent-runtime` for serving, `arcagent-migrate` for schema changes, and `arcagent-build` for builds. Secret grants target individual secrets, not project-wide secret access.
- Artifact cleanup keeps the two most recent versions and removes other images older than seven days. Build-source uploads have a seven-day deletion policy.

`deploy/staging-control.sh` provides explicit `status`, `pause`, and `resume` operations. Set `ARCAGENT_STAGING_PROJECT` to the isolated project before using it. Pause removes public invocation before stopping database compute, retaining data. Storage, retained addresses, backups, and secrets can still incur charges. Resume starts the database before restoring public invocation; application authentication still applies. It does not make a $20 hard cap or disable billing globally. Drain all calls before pausing once real calls are enabled. The script passed `bash -n`; pause/resume were not executed against the new staging environment.

## Observed cloud verification

On September 22, 2026, migration job `arcagent-migrate-dtfcb` completed successfully. Authenticated requests to `/api/console/operations`, `/api/console/calls`, and `/api/console/followups` returned HTTP 200 using the runtime database login. Operations reported database available and voice readiness false. Empty query results represented a real empty database before the synthetic smoke insert, not demo fixtures.

Public `/health` returned 200. Unauthenticated console access returned 401. Voice inbound returned 500 from the existing missing-Twilio-credential validation branch, before any vendor connection. This is blocked ingress, not a successful voice check. Echo and audio-evaluation ingress remain disabled, and coordinator availability is false. No real call, SMS, transcription, model, or speech-synthesis operation was attempted.

The runtime database login is separate from the migration login. It receives PostgreSQL read/write data roles in this isolated instance; it does not receive schema administration. Secret Manager uses a new runtime-only URL version, and the earlier elevated runtime URL version is disabled. The migration credential is held in a separate secret readable only by the migration identity. For production, narrow table/schema grants further instead of using instance-wide predefined data roles.

Transfer reconciliation is available as `scripts/reconcile_transfers.py` but is not scheduled in this deployment. An operator must run its documented bounded workflow when reviewing stale attempts. Cloud deployment does not prove answered/no-answer recovery with the real telephony provider. Approved prompts, vendor credentials, controlled calls, measured audio latency, target-platform backup/restore, and end-user OIDC activation remain required.

The storage execution `arcagent-storage-smoke-t6jzp` succeeded and verified schema revision `d72fc801ab34`, absent runtime superuser/create-role/create-database flags, absent `cloudsqlsuperuser` membership, and no schema ownership. It committed synthetic call ID 1. The follow-up API created a task with HTTP 201, returned the same task on duplicate creation with HTTP 200, resolved it at revision 2, rejected a stale revision with HTTP 409, and returned two audit events. These were real staging database writes using fictional data, not telephone calls. The guarded reusable helper additionally upserts an explicit synthetic display label and only prints its result after commit.

The deployed settings were read back: PostgreSQL `db-f1-micro`, zonal, 10 GiB, storage auto-increase disabled, one retained backup, and no public authorized networks. Cloud Run has one CPU, 512 MiB, concurrency four, maximum one instance, CPU throttling enabled, and startup CPU boost disabled. Minimum scale remains zero. There is no Cloud Run spend-cap enforcement configured; only the $15 alerts budget is active, below the owner's $20 target. All cost forecasts remain estimates with the exclusions and limits described above.

The final guarded storage execution `arcagent-storage-smoke-hjhjh` also succeeded. Both `/api/console/calls/1` and the calls list returned HTTP 200 and included the explicit label `Synthetic staging smoke (not a real call)`. The fixed helper reused the same call instead of creating another. Its import check completed without opening a database session. This completes the staging storage/workflow smoke checks; it does not complete the real-call acceptance gates.

## Deploy the next backend release

GitHub pushes automatically update the Vercel frontend only. The Cloud Run backend is an explicit deployment. Commit and test backend changes first, review `gcloud meta list-files-for-upload`, and record a backup before any migration that affects retained data. Do not deploy during active calls. The following commands reuse the existing resources and secret bindings; run them from the repository root. Stop on any failed build or migration. Review schema compatibility before rollback rather than automatically downgrading.

```sh
(
  set -euo pipefail
  ARCAGENT_RELEASE="$(git rev-parse HEAD)"
  ARCAGENT_IMAGE_URI="us-central1-docker.pkg.dev/arcagent-staging-20260922/arcagent/backend:${ARCAGENT_RELEASE}"
  gcloud meta list-files-for-upload
  gcloud builds submit . \
    --config=deploy/cloudbuild.yaml \
    --substitutions="_IMAGE=${ARCAGENT_IMAGE_URI}" \
    --service-account=projects/arcagent-staging-20260922/serviceAccounts/arcagent-build@arcagent-staging-20260922.iam.gserviceaccount.com \
    --project=arcagent-staging-20260922 --region=us-central1 --quiet
  gcloud run jobs update arcagent-migrate \
    --image="$ARCAGENT_IMAGE_URI" \
    --project=arcagent-staging-20260922 --region=us-central1 --quiet
  gcloud run jobs execute arcagent-migrate \
    --project=arcagent-staging-20260922 --region=us-central1 --wait --quiet
  gcloud run services update arcagent-staging \
    --image="$ARCAGENT_IMAGE_URI" \
    --project=arcagent-staging-20260922 --region=us-central1 --quiet
)
```

These updates deliberately preserve existing runtime environment settings, secret version references, service identities, scaling limits, database integration, and the migration command. The migration job uses its separate schema credential; the runtime continues using the restricted application credential. Record the resulting build ID and resolved image digest, then verify liveness, rejected unauthenticated access, authenticated operations, schema revision, and a permitted workflow. A new secret version does not activate automatically because bindings are pinned; rotate secrets explicitly and verify before disabling old versions. Update the storage smoke helper's expected schema revision deliberately when adding a migration. Its synthetic fixture belongs only in staging.
