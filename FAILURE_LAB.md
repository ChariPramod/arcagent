# Failure laboratory and controlled-call evidence

The project has two different offline checks. Neither establishes real vendor reliability or real caller-perceived latency.

## Deterministic policy simulation

Run all six fictional scenarios from the repository root:

```bash
.venv/bin/python -m scripts.run_failure_lab
.venv/bin/python -m scripts.run_failure_lab --output /tmp/arcagent-failure-report.json
.venv/bin/python -m scripts.run_failure_lab --scenario delayed_transcript --transcript-timeout-ms 4000
```

The output file must not already exist. Reports identify their synthetic provenance. Exit status is zero when all fixed expectations pass, one when an expectation fails, and two for invalid input or an output-file error. The final example deliberately fails the scenario's original late-transcript expectation: increasing its deadline accepts the fictional transcript instead of discarding it.

`evals.replay.scenario_catalog()` exposes metadata. `replay({"scenario_id": "interrupt"})` returns events, actions, assertions and synthetic metrics. `compare_replays({"scenario_id": "vendor_timeout", "candidate_config": {"vendor_timeout_ms": 100}})` produces baseline, candidate and changed fields. Allowed settings are bounded integer vendor timeout, transcript timeout and handoff threshold. Unknown fields and boolean values are rejected.

Scenarios cover silence, interruption, late transcription, vendor timeout, disconnect and unanswered handoff. The handoff calculation invokes production lead scoring. Transport events, timeout behavior, playback cancellation and callback offers in this simulator are a separate illustrative policy model. A green report cannot detect a regression in the real audio session. Synthetic durations are event offsets, not benchmarks. A failing candidate can mean that it no longer exercises the original scenario, not that its configuration is intrinsically unsafe.

## Actual offline integration

```bash
.venv/bin/pytest -q tests/test_controlled_call_workflow.py tests/test_replay_lab.py
```

The controlled workflow exercises production `CallSession`, speech adapters, `GraphResponder`, qualification graph, pure scoring, application finalization, `CallRouter`, `DatabaseTurnSink`, and repository writes to an isolated SQLite database. Only sockets, LLM output and the Twilio client are substituted. The model outputs are validated against real extraction schemas. Playback marks are acknowledged through the actual stream protocol. Temporary test prompt copies use the existing readiness fixture; owner-authored prompts remain unchanged and unapproved.

The four cases demonstrate:

- Qualification persists its lead and score before an accepted transfer request.
- A rejected transfer request leaves the lead and score available, and persists an abandoned outcome.
- An unavailable coordinator routes to a persisted callback slot and queued SMS receipt.
- A caller disconnect during qualification persists abandonment without a lead, transfer or SMS.

These tests also check caller and agent turn persistence, playback timing presence, and hashed inbound numbers. They run without real vendor calls. They do not establish recognition quality, model extraction accuracy, phone delivery, Postgres behavior or latency under load.

## Critical transfer evidence gap

The current `handoff` outcome means the Twilio call-update request accepted the Dial instruction. It does not prove a coordinator answered. There is currently no downstream Dial-result handler that distinguishes answered, busy, no-answer and failed transfers. The simulator's unanswered-handoff callback offer is therefore a proposed recovery policy, not an implemented production recovery path. Transfer request rejection currently preserves the lead for human follow-up; it does not automatically book a fallback callback.

Before claiming answered-transfer reliability, implement and test a verified, idempotent transfer-result callback, distinct attempt and completion state, and a reviewed no-answer recovery policy. Confirm vendor parameters with the owner-authored vendor specification before adding them. Cover duplicate, delayed and out-of-order callbacks and database failures. Do not retry an uncertain transfer or send a follow-up SMS automatically without a recorded, applicable authorization and deduplication mechanism.

## Owner-controlled live verification

Use a dedicated staging environment, approved prompts, fictional details, test numbers you control, and an available coordinator. Confirm credentials, webhook signature verification, retention settings and a bounded spending limit before placing a real call.

1. Record the deployed revision, configuration, call identifier and test scenario without copying credentials or unnecessary caller details into evidence.
2. Complete qualification and check the persisted fields, scoring breakdown and route against the intended fictional case.
3. For an answered case, independently verify the coordinator actually heard the caller. Correlate the provider call legs and terminal statuses with the database. Until the transfer-result handler exists, record this evidence separately and describe database `handoff` as an accepted request only.
4. Repeat with the coordinator unavailable before routing. Confirm exactly one callback slot, the intended destination and the provider's eventual SMS delivery status. Queued is not delivered.
5. Repeat with a coordinator who does not answer. Observe the actual caller experience and provider statuses. Do not expect the simulator's callback offer to occur in production today. Keep a human follow-up available.
6. Interrupt agent speech and disconnect mid-turn. Verify old speech does not resume, tasks end promptly, and the persisted outcome does not claim completion.
7. Capture per-turn timing and missing measurements. Compare repeated runs using the same scenario and configuration; do not treat synthetic duration or one call as a latency guarantee.
8. Inspect for duplicate side effects and unredacted sensitive data. Remove test data according to the configured retention process and stop paid resources when finished.

Passing these checks supports a bounded reliability claim for the tested configuration. No implementation or finite test suite can be guaranteed break-proof.

## Replay against production session behavior

The standalone session adapter closes part of the gap between the policy illustration and actual implementation. It imports no test utilities and requires no credentials:

```bash
.venv/bin/python -m scripts.run_session_replay
.venv/bin/python -m scripts.run_session_replay --output /tmp/arcagent-session-replay.json
.venv/bin/python -m scripts.run_session_replay --scenario interrupt --candidate-barge-in-min-words 4
.venv/bin/pytest -q tests/test_session_replay.py
```

`evals.session_replay.replay_session({"version": 1, "scenario_id": "interrupt"})` executes the real `CallSession` with fixed, versioned synthetic inputs. Scenarios cover interruption, disconnect during synthesis, and a synthesis exception. The adapter uses scripted media, transcript, speech and responder collaborators. Unlike the policy simulator, cancellation, turn recording, output clearing and abandonment decisions are made by production session code.

`compare_sessions` runs the same fixture twice and compares observed behavior. Its only candidate setting is the real `barge_in_min_words` setting, bounded to an integer from one to ten. The interruption fixture supplies a three-word interim transcript. Raising the threshold to four intentionally prevents interruption and fails the fixture's fixed expectation. This is actual configuration-sensitive session behavior, not a generated counterfactual description. It still does not establish that one threshold is universally best.

The event schedule uses phase barriers; timing uses a constant synthetic clock, and latency is explicitly unmeasured. A short watchdog bounds broken runs. Cancellation always awaits session cleanup. Reports contain fixture provenance, a SHA256 digest of the production session source, observed actions, assertions and differences. CLI stdout is JSON, production diagnostic logs go to stderr, and output files cannot be overwritten. Failed assertions return one; invalid inputs or watchdog failures return nonzero.

This adapter bypasses real speech adapters, vendor transports, codecs, LLM extraction, qualification, routing and persistence. The controlled integration tests above cover more layers with other fakes. Neither layer accepts historical caller recordings or claims real-world replay fidelity. Actual audio replay and provider-confirmed transfer outcomes remain future work.
