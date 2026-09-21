# ArcAgent iterative delivery plan

Started September 20, 2026. Continues the data/cloud/validation playbook. The user authorized choosing priorities, delegating work, and implementing them.

## Completed iteration: make controlled voice testing trustworthy

Deliverable: a safer backend and a regression suite that can establish what happened in a conversation before optimizing or deploying it.

| Workstream | Scope | Evidence required | Status |
|---|---|---|---|
| Public endpoint security | Authenticate media WebSocket before vendor work, disable echo by default, protect coordinator controls, clean up partial startup | Rejected requests never start vendors; authenticated sessions close resources | Implemented |
| Caller turn integrity | Preserve finalized segments; flush once at endpoint or utterance end | Scripted call sessions deliver the entire utterance without duplicates | Implemented |
| Playback lifecycle and timing | Associate writer/mark events with the correct utterance; finish terminal audio before teardown | Delayed marks and cancellation do not corrupt another turn's measurements | Implemented |
| Truthful routing | Distinguish failed callback booking from a saved callback whose SMS failed | No claimed booking without a slot, no unintended SMS, persistence errors reported | Implemented |
| Safe audio evaluation | Keep synthetic transport authenticated and prevent real routing effects; stop presenting playback completion as response latency | Explicit isolated mode, refusal by default, no Twilio actions from synthetic calls | Implemented; reply boundary added in next iteration |

Test seams chosen under the user's authorization: HTTP/WebSocket endpoints; CallSession events to responder, persisted turn and outbound audio; CallRouter results and external actions; audio harness to authenticated test transport. Use one failing behavioral test followed by the implementation, then repeat. Mock vendor/network boundaries, not the algorithm being asserted.

## Completed iteration: complete reply boundaries in audio evaluation

Add a test-only logical-reply completion event after every utterance is acknowledged. The client acknowledges individual marks while accumulating the entire reply; the runner checks committed transcript text, invokes the caller once, and stops before generating a response to terminal speech. Missing completion, malformed events, interrupted output, and premature socket closure must fail explicitly. Use the existing session, WebSocket transport, and evaluation-runner seams. Keep the live Twilio protocol unchanged. Status: implemented and verified. Terminal completion is recorded before exposing the event, so an immediate client disconnect cannot reclassify completed playback as abandoned.

## Completed iteration: grade audio conversation quality

The previous runner marked successful transport as a pass without checking qualification. Add a terminal extracted-field snapshot to the isolated protocol; compare expected outcome, handoff decision, and expected fields using the shared metrics; preserve missing evidence as a failure; save expectations and assessment reasons; return a failing CLI status for any failed scenario, including unsaved runs. Test through protocol, assessment, persisted results, and command orchestration. No owner-authored prompts/personas, external routing, or vendor parameters change.

## Current iteration: record effective remote configuration and owner handoff

Capture an allowlisted server configuration for each isolated audio session, including effective prompt hashes, model, scoring threshold, coordinator flag, speech parameters, turn settings, and source hashes. Require a valid handshake; treat CLI prompt/threshold labels as assertions; persist per-scenario evidence and reject mixed configurations as a passing run. Keep credentials and infrastructure addresses out. Record completed work, owner decisions/setup, remaining engineering, and acceptance gates in [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md). This is configuration evidence, not deterministic replay or a live latency claim.

## Next iteration: establish a meaningful conversational baseline

Complete a new prompt version and independent labeled cases, without rewriting owner-authored originals. Verify disclosure and prohibited claims, consent evidence, language fallback, caller number correction, coordinator no-answer, confirmed routing status, and timezone-correct callbacks. Replace placeholder prompt use with an explicit readiness check. Add live vendor smoke checks only after credentials and a spending budget are available.

## Following iteration: measure, then optimize

Record provider first-token versus completed-structured-response timing separately. Establish actual speech-end and first outbound audio timestamps, with clock/correlation semantics. Run a fixed audio benchmark and consenting volunteer calls. Compare endpoint settings and prompt/model changes one at a time against accuracy, interruption errors, latency distributions, and cost. Do not reinterpret legacy playback acknowledgement as first audio heard.

## Staging and operational iteration

Provision a dedicated staging backend and database after the public exposure and controlled-call gates pass. Connect the private website, keep production data separate, test migration/restore, deployment during calls, bounded retries, admission limits and concurrency. Require an explicit spending decision before provisioning new paid services. Keep frontend demo publishing separate from readiness of the voice backend.

## Completion record

Implemented the current workstreams through separate endpoint, turn-integrity, routing, and audio-harness tasks, followed by integration review. Added [VOICE_TESTING.md](VOICE_TESTING.md) for configuration, controlled runs, and measurement interpretation. No dependencies or schema migrations were added. No paid calls, partner data imports, or cloud provisioning were performed.

The regression suite covers authentication before vendor startup, partial vendor startup cleanup, actual graph/session/database simulation without external actions, multi-segment caller speech, interruption and delayed/cleared marks, bounded missing acknowledgements, synthesis failure, callback booking failures, database errors, and delayed evaluation persistence.

Remaining blockers after the first iteration included reply boundaries, now handled by the second iteration. Prompt/persona completion, consent evidence, concurrent slot claiming, confirmed human handoffs, remote configuration provenance, and real speech-end-to-audio latency probes need further implementation. Offline passes establish tested software behavior, not clinical suitability or real-call performance.

Final local verification: `ruff check .` passed; `ruff format --check .` reported `116 files already formatted`; `pytest -q` reported `519 passed, 1 skipped in 2.98s`; `git diff --check` passed. Integration review also added guards for partial disconnect and disconnect before final audio acknowledgement, verified against the real graph/session/database path without external actions.


## Reply-boundary iteration verification

`pytest -q`: `546 passed, 1 skipped in 3.96s`. `ruff check .` passed; `ruff format --check .` reported `118 files already formatted`; `git diff --check` passed. New tests reproduced the previous early-caller behavior before implementation. They cover multi-part greeting and terminal replies, persistence mismatch, missing/malformed completion, incomplete audio, clear events, duplicate marks, closed transport, and immediate disconnect after terminal completion. No dependencies, migrations, paid API calls, or cloud resources were added.


## Audio quality iteration verification

Implemented terminal field snapshots, independent persona-based grading, persisted expectations and failure reasons, and failing CLI exit codes in both saved and unsaved modes. Tests include wrong outcomes despite successful transport, incorrect/excluded fields, absent snapshots, conflicting handoff expectations, mixed repeats, and exit status independent of the database run identifier. Existing historical results are not regraded.

Final local verification: `pytest -q` reported `573 passed, 1 skipped in 4.67s`; `ruff check .` passed; `ruff format --check .` reported `121 files already formatted`; `git diff --check` passed. No dependencies or schema migrations were added, and no paid API calls or cloud resources were used. Remote configuration provenance, prompt/persona completeness, independent audio review, and actual telephony measurements remain outstanding.

CI follow-up: the first GitHub run exposed an overly short integration-fixture deadline during cold SQLite/transport work. Increased only the successful-scenario test deadline, retained the short intentional missing-completion timeout, and left application timeouts unchanged. Local recheck: `573 passed, 1 skipped in 5.60s`; lint and formatting passed.


## Remote configuration and handoff verification

Implemented the authenticated evaluation configuration event, strict schema validation, prompt/threshold assertions, per-scenario persisted metadata, server-derived run labels, and refusal to pass mixed or missing configurations. Captures effective speech/turn/model settings, cached prompt hashes, and on-disk server source hashes without environment secrets. This remains partial provenance, not a deterministic replay bundle; restart after source changes. Added [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) with completed scope, independent owner inputs, credential/data/setup steps, engineering backlog, and staging gates.

Final local verification: `592 passed, 1 skipped in 5.85s`; Ruff lint passed; `125 files already formatted`; `git diff --check` passed. No new dependencies, schema migrations, paid calls, imported real records, or cloud resources.
