# Contact integrations for a dental-group pilot

This implementation serves one dental group with a shared HubSpot account or one shared automation endpoint. Location assignments are workflow context, not tenant isolation. Operator access is group-wide. No provider credentials were configured and no real external delivery was executed during implementation; automated verification uses injected transports.

## What can be sent

An operator explicitly queues a saved call for `hubspot` or `automation`. Queueing writes a durable outbox record and makes no network request. An active assigned location, a contact name, and an international callback number are required. The immutable snapshot contains only name, callback number, and location ID/name. No transcript, clinical information, insurance, scoring, coordinator notes, or inferred email is exported. The existing lead model does not collect email.

HubSpot receives standard contact properties `firstname` and `phone`. The supplied full name is preserved in `firstname` rather than guessing name components. Location context remains in the local delivery/audit record because this implementation does not assume custom HubSpot properties exist. HubSpot branch assignment is manual in the shared group account until the owner deliberately configures and implements a custom property mapping. The automation webhook additionally receives the location snapshot and stable event ID.

The HubSpot contacts API documents contact creation and email as its recommended unique identifier. Because this project does not collect email and has no provisioned custom unique property, this implementation makes a conservative create request rather than claiming phone-based upsert. Different calls from the same person can still produce separate contacts; operator duplicate review is required. A delivery intent is unique per call and destination, including after browser reload or location changes. [HubSpot contact API](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/guide), [HubSpot's maintained contact API implementation](https://github.com/HubSpot/hubspot-api-php/blob/master/codegen/Crm/Contacts/Api/BasicApi.php).

## Configuration and activation

Set server-side `HUBSPOT_ACCESS_TOKEN` with the `crm.objects.contacts.write` scope, or `AUTOMATION_WEBHOOK_URL`. No credential belongs in browser code or GitHub. Readiness reports configuration presence only; it does not probe provider accounts or prove that a workflow runs successfully. `INTEGRATION_DELIVERY_TIMEOUT_S` controls HTTP operation timeouts; the application bounds it to a short interval. A client that loses its response must refresh delivery status rather than assume the send failed.

Accepted automation endpoints are HTTPS Zapier Catch Hook URLs at `hooks.zapier.com/hooks/catch/`, Make cloud hooks at `hook.euN.make.com` or `hook.usN.make.com`, and n8n cloud production webhooks under a single tenant's `*.app.n8n.cloud/webhook/` path. Redirects, credentials embedded in URLs, custom ports, query strings, local addresses, arbitrary domains, and self-hosted n8n are rejected. These restrictions deliberately require a separate reviewed adapter for other destinations. The worker resolves the provider host in a subprocess with a two-second timeout, rejects nonpublic DNS answers, pins the validated public IP, and preserves the original Host and TLS server name. Environment proxies and HTTP redirects are disabled.

HTTPX timeouts apply to individual connection, read, write, and pool operations, not a strict end-to-end wall-clock deadline. A receiver that slowly sends response headers can keep a request active beyond that interval. The sending lease is 120 seconds; lease expiry does not cancel an HTTP request or prove that the receiver did nothing. Recovery marks the record uncertain and fences later local completion updates. It never makes another send safe. Review an uncertain result against the destination even if the original worker later appears to finish.

The shared webhook must route on the supplied location ID, not caller-entered text. Implement durable receiver-side deduplication using `event_id` or the matching `Idempotency-Key` header before triggering downstream actions. This header is a receiver contract, not evidence that Zapier, Make, n8n, or HubSpot automatically deduplicate it. A webhook acknowledgement proves receipt only; it does not prove downstream CRM, email, SMS, or workflow success. [Zapier Catch Hook responses](https://help.zapier.com/hc/en-us/articles/8496288690317-Trigger-Zaps-from-webhooks), [Make webhook queue responses](https://help.make.com/webhooks), [n8n webhook response modes](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).

## Explicit dispatch and recovery

The authenticated console API provides:

- `GET /api/console/integrations`: configuration state without URLs, tokens, or payloads.
- `POST /api/console/integrations/deliveries`: `{call_id, destination, client_request_id}` queues an intent. The same intent returns the existing record. Rebinding a request ID to another intent is rejected.
- `GET /api/console/integrations/deliveries`: bounded paging and optional `location_id` filter over immutable location snapshots.
- `POST /api/console/integrations/deliveries/{id}/send`: `{confirm_delivery: true, expected_attempt_count}` attempts one due queued delivery, using the verified operator identity. It does not retry within the request.

The operator worker is also available:

```sh
python -m arcagent.integrations.worker
python -m arcagent.integrations.worker --send --limit 10
```

The first command is a read-only preview of due IDs. `--send` is an explicit external-action command; use only with an approved destination and contact data. It also converts expired `sending` claims to `uncertain`. There is no scheduled worker or automatic onboarding delivery. A changed destination credential/URL, deactivated location, or changed location assignment blocks sending rather than silently using a different destination or clinic.

The API's explicit send route does not sweep stale claims. In this release, stale recovery happens only when an operator runs the worker with `--send`; that command can also send other due queued records, up to its limit. The dry-run command does not recover claims. A stuck sending row can therefore remain pending indefinitely without this operational step. Plan an approved operator procedure rather than assuming a background scheduler is running.

Contact corrections update the lead, not an already queued delivery snapshot. Confirm the contact fields shown on the delivery before sending. A new queue request for the same call and destination returns the existing snapshot, even after a correction. The current API has no cancellation or replacement operation for an incorrect queued snapshot; do not send it and do not delete/recreate it to bypass duplicate protection. Safely replacing a never-dispatched intent requires a separately reviewed operation.

The worker atomically claims a queued record and commits before network activity. Competing workers cannot claim the same attempt. Success is recorded only after the provider response: HubSpot HTTP 201 or an automation HTTP 2xx acknowledgement. Outbound bodies and provider response bodies are never logged, and response bodies are not buffered. Authenticated delivery-list responses expose the snapshotted contact name/phone for explicit operator confirmation; they omit raw payloads and the configuration fingerprint.

HubSpot HTTP 429 is treated as a rate-limit rejection, with delayed retries and a maximum of three attempts. A destination-resolution failure before any request uses the same bounded retry policy. The worker sends at most once per invocation of a record; later eligible invocations perform the remaining attempts. Other known HubSpot request rejections stop as `failed`. Network exceptions, 5xx, redirects, unexpected HubSpot statuses, and non-2xx automation responses become `uncertain`; they never automatically retry. Automation endpoints can execute downstream work before returning an error, so generic webhook errors cannot safely establish absence of side effects. [HubSpot error handling](https://developers.hubspot.com/docs/api-reference/error-handling).

A process crash or database failure after sending leaves a `sending` claim until the next explicit worker recovery classifies it as uncertain. Late results cannot overwrite a recovered claim. Terminal `failed` and `uncertain` records are deliberately not requeued through the current API. Review the provider account using the contact details and timestamps, resolve the operational follow-up, and reconcile manually. Do not delete/recreate outbox rows to force a resend. A later reviewed retry/reconciliation feature must distinguish confirmed absence from unknown acceptance.

Before restoring an older database backup, suspend external dispatch and reconcile its queued/sending records against provider history. A backup predating remote acceptance can otherwise replay work. This design reduces duplicates during normal operation; it does not claim distributed exactly-once delivery or make externally triggered automation harmless.
