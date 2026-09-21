# ArcAgent iterative delivery plan

Started September 20, 2026. Continues the data/cloud/validation playbook. The user authorized choosing priorities, delegating work, and implementing them.

## Current iteration: make controlled voice testing trustworthy

Deliverable: a safer backend and a regression suite that can establish what happened in a conversation before optimizing or deploying it.

| Workstream | Scope | Evidence required | Status |
|---|---|---|---|
| Public endpoint security | Authenticate media WebSocket before vendor work, disable echo by default, protect coordinator controls, clean up partial startup | Rejected requests never start vendors; authenticated sessions close resources | Implemented |
| Caller turn integrity | Preserve finalized segments; flush once at endpoint or utterance end | Scripted call sessions deliver the entire utterance without duplicates | Implemented |
| Playback lifecycle and timing | Associate writer/mark events with the correct utterance; finish terminal audio before teardown | Delayed marks and cancellation do not corrupt another turn's measurements | Implemented |
| Truthful routing | Distinguish failed callback booking from a saved callback whose SMS failed | No claimed booking without a slot, no unintended SMS, persistence errors reported | Implemented |
| Safe audio evaluation | Keep synthetic transport authenticated and prevent real routing effects; stop presenting playback completion as response latency | Explicit isolated mode, refusal by default, no Twilio actions from synthetic calls | Implemented; response-boundary limitation below |

Test seams chosen under the user's authorization: HTTP/WebSocket endpoints; CallSession events to responder, persisted turn and outbound audio; CallRouter results and external actions; audio harness to authenticated test transport. Use one failing behavioral test followed by the implementation, then repeat. Mock vendor/network boundaries, not the algorithm being asserted.

## Next iteration: establish a meaningful conversational baseline

First add logical-response completion signaling to the isolated audio protocol, including multi-utterance terminal replies. Then complete a new prompt version and independent labeled cases, without rewriting owner-authored originals. Verify disclosure and prohibited claims, consent evidence, language fallback, caller number correction, coordinator no-answer, confirmed routing status, and timezone-correct callbacks. Replace placeholder prompt use with an explicit readiness check. Add live vendor smoke checks only after credentials and a spending budget are available.

## Following iteration: measure, then optimize

Record provider first-token versus completed-structured-response timing separately. Establish actual speech-end and first outbound audio timestamps, with clock/correlation semantics. Run a fixed audio benchmark and consenting volunteer calls. Compare endpoint settings and prompt/model changes one at a time against accuracy, interruption errors, latency distributions, and cost. Do not reinterpret legacy playback acknowledgement as first audio heard.

## Staging and operational iteration

Provision a dedicated staging backend and database after the public exposure and controlled-call gates pass. Connect the private website, keep production data separate, test migration/restore, deployment during calls, bounded retries, admission limits and concurrency. Require an explicit spending decision before provisioning new paid services. Keep frontend demo publishing separate from readiness of the voice backend.

## Completion record

Implemented the current workstreams through separate endpoint, turn-integrity, routing, and audio-harness tasks, followed by integration review. Added [VOICE_TESTING.md](VOICE_TESTING.md) for configuration, controlled runs, and measurement interpretation. No dependencies or schema migrations were added. No paid calls, partner data imports, or cloud provisioning were performed.

The regression suite covers authentication before vendor startup, partial vendor startup cleanup, actual graph/session/database simulation without external actions, multi-segment caller speech, interruption and delayed/cleared marks, bounded missing acknowledgements, synthesis failure, callback booking failures, database errors, and delayed evaluation persistence.

Remaining blockers are explicit: the audio caller still treats utterance marks as reply boundaries; prompt/persona completion, consent evidence, concurrent slot claiming, confirmed human handoffs, independent outcome scoring, and real speech-end-to-audio latency probes need further implementation. Offline passes establish tested software behavior, not clinical suitability or real-call performance.

Final local verification: `ruff check .` passed; `ruff format --check .` reported `116 files already formatted`; `pytest -q` reported `519 passed, 1 skipped in 2.98s`; `git diff --check` passed. Integration review also added guards for partial disconnect and disconnect before final audio acknowledgement, verified against the real graph/session/database path without external actions.
