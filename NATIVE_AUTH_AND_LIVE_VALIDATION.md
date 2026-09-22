# Native sign-in and controlled live-call milestone

## Implemented

Native Vercel authentication uses OpenID Connect authorization-code flow with PKCE, state, nonce, and signed ID-token verification. Google is the selected provider. The existing Sites identity integration remains separate; a native Vercel request cannot authenticate itself by supplying Sites identity headers.

Sessions and login transactions are authenticated and encrypted HTTP-only, Secure, SameSite=Lax cookies. They bind to the configured site origin, identity issuer, and client ID. Transactions expire after 10 minutes; sessions after 15 minutes. Provider access tokens and ID tokens are not stored in the browser session. Display names never authorize access. Stable account IDs hash the verified issuer and subject.

Workspace access and the server-side API proxy independently enforce `ARCAGENT_ALLOWED_USER_IDS`. A successfully authenticated but unapproved user sees their account ID and no call records. Logout requires a same-origin POST. Sign-in errors clear the login transaction and offer a safe retry without exposing provider error details.

Transfer intent is committed before asking Twilio to redirect a call. Acceptance of that request is **not** success. Duplicate dispatch does not redial. Explicit rejection is distinguished from an ambiguous timeout; uncertain requests stay unresolved and create a recovery record. The SDK has a bounded HTTP timeout and no automatic retries.

Transfer callbacks always require valid Twilio signatures, including development. They also check account, parent/child identity, sequence, and bridge evidence. Progress is deduplicated and can arrive out of order. A child call finishing alone is insufficient. Only a completed Dial result with positive bridge evidence records handoff. Completed-but-unbridged, busy, no-answer, failure, and cancellation create staff recovery. Database failure returns a retryable response, rather than acknowledging uncommitted evidence.

Call detail exposes transfer evidence without vendor identifiers. The final conversation write cannot overwrite a callback outcome. Schema migration: `d72fc801ab34` after `c21ab845df10`.

## What remains unproven

A confirmed bridge is not proof of a human coordinator. Voicemail or an answering system can answer. Human acknowledgement, a controlled observation, or a separately designed screening flow is still needed. No unapproved answering-machine-detection parameters were added.

No real phone call has been completed in this iteration. Automated tests use controlled vendor boundaries and signed synthetic callbacks. They do not establish real vendor latency, audio quality, network reliability, or human transfer success.

Logout deletes the browser cookie; it does not revoke a copied cookie at the server. A copied session remains valid until expiry. Removing the account from the configured allowlist denies later workspace/API access; rotating the cookie key invalidates all sessions. A durable individual-session registry is a later improvement.

Transfer recovery preserves existing staff assignment, notes, and task status. If a staff member already completed a task, later transfer recovery appears in its audit rather than silently reopening it. Recovery is not a booked callback or a promise of an SMS. Failed transfers currently speak a neutral failure message and hang up; intake does not automatically resume.

## Finish Google sign-in

A guided, machine-local setup script is available at `/tmp/arcagent-google-signin.sh`. Run it in Terminal with `bash /tmp/arcagent-google-signin.sh`. It opens the relevant dashboards, captures the client secret with hidden input, saves ignored local configuration, publishes server-only Vercel variables, and lets you approve your account. It was syntax-checked, not run through your account-owned registration steps. It is intentionally outside the public repository.

The durable manual procedure is:

1. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview?project=arcagent-staging-20260922) in the isolated ArcAgent project. Configure app branding, your support email, and a staging/test audience. Add your test account if Google requires it.
2. In [Clients](https://console.cloud.google.com/auth/clients?project=arcagent-staging-20260922), create a **Web application** OAuth client. Register exactly `https://arcagent-beige.vercel.app/auth/callback` as an authorized redirect URI. This is a server authorization-code flow; no Gmail, Drive, Calendar, or offline scope is requested.
3. Put the following server-only variables in Vercel production. Do not paste secrets into chat, source files, or Git. The callback must use the fixed production alias, not an arbitrary preview hostname.

| Variable | Value |
| --- | --- |
| `ARCAGENT_AUTH_ORIGIN` | `https://arcagent-beige.vercel.app` |
| `ARCAGENT_OIDC_ISSUER` | `https://accounts.google.com` |
| `ARCAGENT_OIDC_CLIENT_ID` | Google web client ID |
| `ARCAGENT_OIDC_CLIENT_SECRET` | Google web client secret |
| `ARCAGENT_AUTH_SECRET` | Independent random 32-byte base64url key |

Generate the key locally with `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`. Never reuse the backend API token.

4. Redeploy, open `/workspace`, and sign in. Copy your `oidc:` account ID from the access-pending screen into the comma-separated `ARCAGENT_ALLOWED_USER_IDS` variable. Preserve any other approved IDs, redeploy, and retry. Google sign-in alone does not grant workspace access.
5. Verify unauthenticated private API requests return 401, an unapproved account cannot read records, and sign-out returns you to the public site. Configure a separate client/origin for a separate preview deployment if needed.

The flow and registration steps are based on [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect) and [Google web client setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid). Token handling uses [openid-client](https://github.com/panva/openid-client) and its explicit [signature verification checks](https://github.com/panva/openid-client/blob/main/docs/functions/enableNonRepudiationChecks.md), plus [jose](https://github.com/panva/jose) for encrypted cookies.

## Complete backend configuration

The backend is deployed at `https://arcagent-staging-ydan5h6udq-uc.a.run.app` with a migrated persistent PostgreSQL database. Live checks verified health, rejection of unauthenticated console access, authenticated reads, and a synthetic follow-up create/retry/resolve/conflict/audit sequence. Runtime database privileges were checked separately from migration credentials. These checks establish cloud persistence, not real phone integration.

See [CLOUD_STAGING.md](CLOUD_STAGING.md) for actual cloud resources, costs, deployment status, and teardown. Cloud infrastructure has a $20/month staging target. Speech, telephony, and model usage are separate and are not activated by this infrastructure budget.

Before enabling calls, place the real provider configuration in Secret Manager and bind it to the backend revision: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER`, `COORDINATOR_NUMBER`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, and `LLM_API_KEY`. Verify the configured model identifiers are available to your accounts. Keep the existing owner-approved vendor parameters unless deliberately reviewed.

Set `PUBLIC_URL` to the backend's exact external HTTPS origin. Keep `ENV=prod`, signature validation enabled, echo disabled, and audio-evaluation ingress disabled. Vercel's `ARCAGENT_API_URL` points to this backend; `ARCAGENT_API_TOKEN` must match the backend console token. Never expose either through `NEXT_PUBLIC_` variables. The database and admin tokens remain separate.

Migration and readiness must pass before routing a real number. Health only proves the process is running; readiness does not prove vendor credentials actually work. A service with missing vendor secrets can safely expose health and authenticated console infrastructure while remaining blocked for real-call acceptance.

## Controlled phone-call acceptance

Owner input is also required before a meaningful call: the current protected prompt files contain `TODO_OWNER`, and the owner persona suite is not populated. Complete and approve those conversation instructions, business rules, escalation wording, and expected labels before a paid benchmark. The automated fixtures do not substitute for clinic approval. See [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) and [VOICE_TESTING.md](VOICE_TESTING.md).

Use consenting test participants and synthetic lead details. Obtain the applicable recording/transcript consent and clinic approval before testing with patient information. Choose a reachable coordinator number and explicitly arrange the test window. Do not import real clinic enquiry records just to test routing.

Configure the Twilio number's inbound voice webhook to `POST {PUBLIC_URL}/voice/inbound`. Transfer TwiML supplies its own signed action and child-status callback URLs. The owner approved the new documented transfer parameters in this session. The implementation uses Dial action/method/timeout and Number status callbacks; `answerOnBridge` is unnecessary for an already answered Media Stream call. See [Dial](https://www.twilio.com/docs/voice/twiml/dial), [Number](https://www.twilio.com/docs/voice/twiml/number), and [signature validation](https://www.twilio.com/docs/usage/webhooks/webhooks-security).

For every trial, record the deployed Git SHA/image, test case, call ID, region, provider/model configuration, expected result, actual result, and coordinator observation. Keep detailed call artifacts in private storage; commit only de-identified findings. Do not call a case passed merely because the HTTP transfer request succeeded.

| Trial | Required evidence |
| --- | --- |
| Coordinator answers | Request is initially pending/accepted; signed result confirms bridge; coordinator independently confirms hearing caller; no duplicate dial |
| Coordinator does not answer | No-answer evidence, no handoff, recovery task/audit, neutral caller fallback |
| Busy or rejected call | Correct failure evidence and one recovery task; no automatic retry |
| Voicemail answers | May be a confirmed bridge; explicitly fail the human-answer acceptance check |
| Caller hangs up while dialing | Observe available child/action evidence; if unresolved, queue stale review; do not invent success |
| Provider/update timeout | Uncertain state, no automatic redial, later callback can reconcile |
| Duplicate/out-of-order callback | One durable terminal decision and recovery; no status regression |
| Invalid signature/account/child | Rejected before outcome mutation |
| Database outage during callback | Retryable failure, never a success acknowledgement before commit |
| Silence, interruption, and slow speech | Verify reprompt/hangup, barge-in cancellation, and no overlapping/stale audio |

The invalid-callback and outage trials should use a controlled staging test harness, not an attack on the live number. Never disable signature checking to make a test pass.

## Measure latency honestly

Use the call detail timing view and authenticated `/api/console/calls/{id}/latency` report. Report missing measurement coverage alongside available p50/p95 stage timings. A Twilio playback acknowledgement is not the time the first audio reached the caller. Do not add unrelated stage aggregates and label the sum end-to-end latency.

For perceived response latency, capture a controlled observation from the end of the caller's speech to first audible agent audio with one consistent measurement method. Separate cold starts from warm calls and record region/network conditions. Tune one variable at a time, rerun the same scenarios, and retain interruption and silence cases as regression gates. Provider endpointing changes still require review against the owner-maintained vendor specification.

## Reconcile unresolved transfers

From an authorized runtime with database access:

```sh
python -m scripts.reconcile_transfers --older-than-minutes 60 --limit 100
python -m scripts.reconcile_transfers --older-than-minutes 60 --limit 100 --apply
```

The first command is read-only. The second creates bounded recovery work; neither calls a vendor or redials. Choose an age greater than the expected longest call. This command is not yet scheduled automatically. Monitor its exit status and review the queue; an existing completed staff task retains its status.

## Validation in this iteration

- Backend: `733 passed, 1 skipped in 8.44s`. The opt-in vendor integration test remains skipped; no live vendor result is implied.
- Python and frontend lint checks, plus Python formatting, passed. GitHub CI is green for the implementation.
- Frontend: `40 passed, 0 failed`.
- TypeScript, native Next.js production build, and the existing Sites build passed.
- New dependencies: `openid-client` for standards-based OIDC and explicit ID-token signature verification; `jose` for authenticated encrypted cookies.
- No real-call, live Google OAuth, or human-answer result is claimed by these tests.
