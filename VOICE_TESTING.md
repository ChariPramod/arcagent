# Controlled voice testing

This guide covers the first reliability iteration. See [ITERATION_PLAN.md](ITERATION_PLAN.md) for the delivery sequence and [the playbook](DATA_CLOUD_AND_VALIDATION_PLAYBOOK.md) for data sourcing and costs.

## Environments and credentials

Use a separate database for synthetic audio evaluations. The evaluation server writes simulated call outcomes into its own calls table. These are not evidence that a coordinator answered or a callback was booked. Do not connect this database to a production workspace.

| Setting | Purpose |
|---|---|
| `ENV=prod` | Enforces Twilio signature validation even if the development bypass flag is false |
| `TWILIO_AUTH_TOKEN` | Verifies webhook and media WebSocket signatures |
| `PUBLIC_URL` | Public HTTPS origin used for signature validation behind a proxy |
| `ADMIN_API_TOKEN` | Separate bearer credential for reading/changing coordinator availability |
| `CONSOLE_API_TOKEN` | Read-only website API credential; does not authorize coordinator changes |
| `ECHO_ENABLED` | Defaults to false. Explicitly enabled echo still requires Twilio authentication |
| `ENV=test` | Required for the isolated audio-evaluation route |
| `ENABLE_AUDIO_EVALS=true` | Explicitly enables that route in the test environment only |
| `AUDIO_EVAL_TOKEN` | Independent bearer credential for the synthetic caller |

Keep all tokens in environment variables or ignored local configuration. Do not put them in URLs, shell history, datasets, or Git. Use independent random values for independent capabilities.

## Actual Twilio calls

The incoming number's webhook remains `POST /voice/inbound`. Media connects to `/voice/stream`. Both require valid Twilio signatures. The server rejects an unauthenticated stream before accepting it or opening speech-vendor sockets. Signatures use the externally visible URL; configure the public origin correctly rather than disabling validation when a proxy changes the internal host.

`/voice/echo` is disabled by default and, when enabled, uses the same signature requirement. `/admin/coordinator` requires `Authorization: Bearer <ADMIN_API_TOKEN>` for both reads and changes. Missing admin configuration fails closed. This is a single-workspace administrative capability, not multi-tenant RBAC or a complete audit trail.

Official contract: [Twilio Media Streams authentication](https://www.twilio.com/docs/voice/media-streams), [signature validation and WebSocket trailing slash guidance](https://www.twilio.com/docs/usage/security).

## Synthetic audio evaluations

The harness now uses `/eval/voice/stream`, never `/voice/stream`. The dedicated route requires all three of `ENV=test`, explicit enablement, and a matching evaluation token. It is unavailable in development or production regardless of the token. Real speech/LLM APIs still incur charges; only the telephony routing actions are disabled.

On a dedicated test backend:

```text
ENV=test
ENABLE_AUDIO_EVALS=true
AUDIO_EVAL_TOKEN=<independent-random-secret>
DATABASE_URL=<isolated-test-database>
DEEPGRAM_API_KEY=<test-project-key>
CARTESIA_API_KEY=<test-project-key>
CARTESIA_VOICE_ID=<agent-voice>
LLM_API_KEY=<test-project-key>
```

Apply database migrations and start the backend. The harness process needs the same test database and evaluation token, plus its own model/TTS access. Populate reviewed personas and use a complete prompt version before attempting to measure conversation quality. Existing owner-authored prompt files and personas were not rewritten in this iteration.

```bash
.venv/bin/alembic upgrade head
.venv/bin/uvicorn arcagent.app:app --host 127.0.0.1 --port 8000
```

In a second terminal configured for the same test environment:

```bash
.venv/bin/python -m evals.run_audio \
  --run-name controlled-audio-baseline \
  --stream-url ws://localhost:8000/eval/voice/stream \
  --caller-voice YOUR_DIFFERENT_CALLER_VOICE \
  --groups hot_buyers --n 1
```

The client sends the evaluation credential in a header. It refuses the live voice path, credentials or tokens embedded in URLs, query strings, and unencrypted non-loopback URLs. Remote evaluation requires WSS and a separately deployed test server. The route never invokes `CallRouter`, reserves slots, transfers calls, or sends SMS. Its call outcome is a simulated graph/session outcome.

The harness waits for the freshly acknowledged agent turn to appear in the database, rather than feeding its caller model stale transcript text. Incomplete audio or missing committed conversation state must be reported as failures. Per-scenario infrastructure errors should leave an inspectable result without disclosing credentials or raw exception payloads.

Known blocker for a reliable conversational audio benchmark: a mark identifies one TTS utterance, not an entire logical reply. The simulated caller can answer before a multi-part reply finishes. A terminal server close can also conservatively fail a scenario if the simulated caller attempts another response. Add explicit logical-response completion signaling and a terminal multi-part regression before interpreting this harness as a quality or release gate. The current transport and persistence checks remain useful integration diagnostics.

## What the measurements mean

The fake Twilio client acknowledges received frames and marks. It is not a phone speaker and does not simulate actual carrier playback timing. Stage values are useful for integration diagnostics, not a caller-perceived latency claim.

- `playback_start_ms` is a legacy database name for first frame written to matching playback acknowledgement. It is not first audio heard. Cleared or unacknowledged audio has no completed-playback measurement.
- Response-latency p50/p95 are left unavailable by the audio runner. Earlier versions incorrectly used playback acknowledgement for them.
- `stt_final_ms` still uses a last-media-frame anchor; it is not a reliable physical speech-end measurement.
- `llm_ttft_ms` at the session layer still reflects the responder's first yielded text, which follows structured graph work. Propagating provider first-token timing remains a separate task.
- Caller segment assembly and per-utterance playback correlation improve correctness; they do not establish a measured latency improvement.

An audio result without transport errors is still not sufficient evidence of correct qualification. Add expected-field/outcome checks, independent audio review, scenario snapshots, and real-phone probes before using audio results as a deployment gate. The existing text benchmark retains its stricter compatibility checks and guarded metrics.

## Routing outcomes

A missing callback number or unavailable callback slot now produces a failed/abandoned outcome rather than a fictitious booking. A callback that was actually reserved remains booked if SMS sending or SMS-receipt persistence subsequently fails, with an error that needs operational attention. A pre-action database failure prevents external actions. Unfinished conversations, silence abandonment, and disconnect before terminal playback acknowledgement cannot trigger routing.

These changes do not implement consent capture, atomic slot claiming under concurrent Postgres transactions, provider delivery callbacks, or a confirmed coordinator-answer state. A successful transfer update request is still distinct from a completed human handoff. Do not automatically retry an ambiguous external action without idempotency/reconciliation.

## Verification and next gate

Run the full offline suite before a live experiment:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

No vendor keys or paid API calls are required for these checks. They exercise simulated transport and injected vendor responses. Actual vendor interoperability, network latency, healthcare readiness, and cloud capacity remain unverified until explicit controlled runs establish them.
