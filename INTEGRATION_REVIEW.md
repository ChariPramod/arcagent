# Reviewing uncertain CRM deliveries

Operators can now record what they found after investigating a failed or uncertain contact export. This is a separate human review record. It does not resend the contact, change the provider delivery status, or turn an authentication failure into a machine-confirmed delivery.

## Operator workflow

Open the delivery and inspect the destination's records before reviewing it. For a stale `sending` record, first use the explicit stale-recovery action. Recovery checks the existing sending lease, changes expired claims to `uncertain`, and records the acting operator. It performs no external HTTP requests and leaves current claims alone. An old worker response cannot overwrite recovered state because completion is fenced by the attempt and status.

Choose one of these human-reported resolutions:

- `verified_received`: the operator found external evidence of receipt.
- `verified_not_received`: the operator investigated and reports no receipt.
- `needs_followup`: investigation is incomplete or further staff work is required.

Write a short evidence note or an external record reference. Do not paste credentials, transcripts, clinical details, or full contact records. The note is stored as operator-entered text and displayed only in the authenticated workspace; references are not fetched. The application does not independently verify the operator's statement.

Provider status remains visible beside the review. `uncertain` stays uncertain and `failed` stays failed, including after a `verified_received` review. This deliberate separation prevents staff assertions from being confused with a provider acknowledgement. Review history is append-only through the application API; a correction is another review, not an edit of the earlier record. Database administrators still have database-level capabilities, so this is not cryptographic tamper evidence.

## API contract

All paths below are under `/api/console/integrations`. They require the console credential; writes also require the trusted actor supplied by the authenticated website proxy. The browser does not possess the console bearer token.

`POST /deliveries/{id}/reviews` accepts:

```json
{
  "client_request_id": "a new UUID retained for retries of this exact action",
  "expected_status": "uncertain",
  "expected_attempt_count": 1,
  "expected_review_revision": 0,
  "resolution": "needs_followup",
  "evidence": "Synthetic example: operator is awaiting destination support confirmation."
}
```

The request identifier above is explanatory; callers must generate an actual UUID. `expected_status` permits only `failed` or `uncertain`. Evidence is trimmed, required, and limited to 1000 characters. Extra fields, invalid statuses, and invalid request shapes are rejected without echoing the request body. Review input and database failures produce sanitized errors.

Creation returns `201` and a review object with `id`, `delivery_id`, `provider_status`, `attempt_count`, `review_revision`, `resolution`, `evidence`, `created_by`, and `created_at`. A replay by the same actor using the same UUID and exact normalized request returns the original object with `200`, even if a later review exists. A rebound UUID or stale expected state returns `409`. After an uncertain response, refresh records before deciding whether to retry; preserve the original request UUID for an exact retry.

The database transaction atomically checks provider state, attempt count, and independent review revision, increments only that review revision, inserts the review, and appends a workflow audit event. It never changes the delivery payload, next attempt, attempt count, or provider status. Audit changes contain review identity, resolution, provider-state snapshot, and revision; the evidence note is not duplicated into the activity feed.

`GET /deliveries` adds `review_revision` and `latest_review` to each row. Latest reviews are loaded in a batch for the current page, without a query per delivery. `GET /deliveries/{id}/reviews?limit=50&offset=0` returns newest-first history, total, limit, and offset. The maximum history page size is 100.

`POST /deliveries/recover-stale` accepts `{"confirm_recovery":true,"limit":100}`. The limit must be from 1 to 100. It returns `{"recovered":N,"external_requests":false}`. This is a group-wide bounded recovery of expired claims, not just the currently displayed location. Repeating recovery is safe because only still-expired `sending` claims qualify. No external provider configuration is required to record a review or recover a stale claim.

## Database and release

Migration `h16de235ef78`, following `g05cf124de67`, adds `integration_deliveries.review_revision` with an existing-row default and the `integration_reviews` table. Apply the migration before deploying schema-dependent code. Review rows reference deliveries and are removed if an explicitly deleted delivery cascades; the transcript retention command does not delete deliveries or reviews. The downgrade removes review history, so use ordinary backup and migration review practices before rolling it back.

This feature adds no dependency, cloud resource, scheduler, automatic retry, or terminal-delivery requeue. It does not deduplicate separate calls representing the same person. See [integration setup](INTEGRATIONS_SETUP.md) for existing dispatch, destination configuration, and acknowledgement limits.

## Validation and limits

Focused tests cover terminal-state eligibility, normalized request replay, UUID rebinding, staff concurrency, stale revisions, atomic audit rollback, provider-state preservation, authenticated access, sanitized validation errors, latest-review query shape, bounded history and recovery, lease protection, old-worker fencing, and migration upgrade/downgrade. Recovery and review tests use synthetic local data and injected transport guards; no external contact export is performed.

Source: [review transaction](arcagent/integrations/reviews.py), [API](arcagent/integrations/api.py), [models](arcagent/persistence/integration_models.py), [worker recovery](arcagent/integrations/worker.py), and [tests](tests/test_integration_reviews.py). These local checks are not evidence of a deployed migration, an external destination receipt, or an independently verified business outcome.
