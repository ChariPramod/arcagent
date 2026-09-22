# ArcAgent build status and owner handoff

Updated September 21, 2026. This is the practical handoff for the current repository, not a claim of production readiness. Read it alongside [the iteration log](ITERATION_PLAN.md), [controlled voice testing](VOICE_TESTING.md), [the data/cloud playbook](DATA_CLOUD_AND_VALIDATION_PLAYBOOK.md), and [website setup](web/SETUP.md).

## Current position

The repository contains a working application skeleton, a premium website and review console, deterministic regression tests, and increasingly strict text/audio evaluation tooling. It does **not** yet have a validated live conversational benchmark or a production-ready dental intake service.

The most immediate blockers are concrete:

- All seven prompt files under `arcagent/agent/prompts/v1/` still contain `TODO_OWNER`.
- `evals/personas/` contains a template and instructions, but no runnable owner personas. Test fixtures and delivery mutations are separate synthetic suites; they do not fill this gap.
- Real speech/vendor interoperability, actual telephone latency, and production operational behavior have not been established by the offline tests.
- Account access, spending limits, business policies, approved data, and independent labels require your decisions.

Do not pay for a benchmark using the current placeholder prompts. Do not describe synthetic handoff or callback outcomes as completed external actions.

## What has been built

| Area | Implemented | What that establishes |
|---|---|---|
| Voice pipeline | FastAPI, Twilio media transport, Deepgram recognition, graph-based conversation, Cartesia speech, persistence | Application integration and tested lifecycle behavior |
| Decision logic | Deterministic qualification scoring and routing rules | The model does not choose the hot/cold threshold |
| Text evaluations | Saved persona/prompt inputs, hashes, transcripts, guarded comparisons, delivery-mutation fixtures | Inspectable text experiments with compatibility checks |
| Website | Product landing page, fictional demo, authenticated read-only workspace, call/evaluation review, backend proxy | A product interface; connecting live data is a separate setup step |
| Endpoint protection | Media authentication before vendor startup, protected coordinator administration, disabled-by-default echo | Tested rejection and capability separation |
| Turn handling | Finalized transcript segment assembly, boundary handling, interruption cancellation, per-utterance mark ownership | Regression coverage for lost segments and playback races |
| Failure handling | Bounded acknowledgement waits, synthesis cleanup, partial startup cleanup, safe disconnect behavior | Tested failure paths do not silently become successful routing |
| Routing truth | Missing slots/numbers fail; persisted callbacks remain booked when SMS subsequently fails; database errors reported | More accurate distinction between booking and notification |
| Isolated audio tests | Dedicated authenticated test route, simulation provenance, no router/SMS/transfer actions | Synthetic tests cannot intentionally execute real routing through this route |
| Complete reply boundaries | Acknowledges each audio chunk but waits for the logical reply; terminal replies stop the simulated caller | Prevents premature responses and terminal close races |
| Audio grading | Expected outcome, handoff, and field checks; missing evidence fails; expectations and reasons saved | Transport success alone no longer passes an evaluation |
| Input readiness | Offline preflight, required-prompt validation, empty-suite rejection, entrypoint guards | Detects missing/placeholder inputs; not semantic approval |
| Command behavior | Failed audio cases produce a failing exit status, including `--no-db` | Evaluation failures can be used by automation |
| Configuration provenance | Server-reported configuration and hashes, validation and persisted evidence | Records the configuration reported for an audio session; see the current testing guide for the exact contract |

Recent milestone commits before the configuration iteration: `f6d3d99` (text evidence and mutations), `15e1411` (website), `f5497a3` (data/cloud playbook), `a6c02cb` (voice safety), `95417bc` (complete replies), `cc1d190` (audio grading), and `aa3eaff` (CI fixture deadline). Use Git history and the iteration log for the latest configuration commit and verification record.

These iterations added no new paid services and made no paid test calls. No real enquiry data was imported. Existing owner-authored prompts and personas were preserved.

## What you need to provide or decide

### Business behavior and approved wording

Review the existing scoring and conversation design documents. Supply decisions on which treatments are in scope, what the assistant may say about pricing and insurance, coordinator hours, callback availability/timezone, escalation paths, unsupported languages, and how a caller can decline further contact.

Review disclosure, recording, and data-use wording with the appropriate owner before real callers are involved. This document does not establish permission to process patient data. The earlier playbook links the relevant official guidance and vendor sources.

**Deliverable:** written accepted behavior for normal calls and exceptions, plus reviewed prompt text. I can create a new prompt version and implement readiness checks once those decisions are available. A new version preserves the original owner files. The existing repo instructions reserve `evals/personas/` for your independent cases.

### Independent benchmark labels

Create actual persona YAML files from `evals/personas/_template.yaml`, following its schema and `evals/personas/README.md`. Use fictional identities and phone numbers. Decide expected fields, expected outcome, and expected handoff before inspecting the agent's output. Keep `expected.handoff` consistent with the intended outcome. List fields the caller never provides in `not_expected` deliberately; do not use exclusions to hide extraction errors.

Cover hot and cold leads, price/fear/logistics objections, correction of a phone number or name, incomplete contact information, caller refusal, wrong number, existing patient, unsupported language, missing coordinator, silence, interruption, noise, and slow speech. Some failures need transport tests or volunteer audio in addition to text personas. Reserve unseen cases and speakers for final evaluation.

The repository describes an intended thirty-persona benchmark, but those files are not present. Do not mistake passing fixture tests for passing that benchmark.

**Deliverable:** runnable independently reviewed personas, a development/held-out split, and accepted success/failure criteria. I can validate the files and add tooling, but your independent judgment is part of the evidence.

### Vendor access and spending limits

You need account access for the selected speech, model, and telephony providers. Set credentials in ignored local environment files or deployment secrets; never send keys in a chat, commit them, or place them in a URL.

For synthetic audio, configure Deepgram, Cartesia, the current Anthropic model backend, an agent voice, a distinct caller voice, and a dedicated evaluation token. Confirm available models and voices in your accounts before running; repository defaults are configuration, not a guarantee of current account entitlement.

For real phone testing, additionally configure a Twilio number, account credentials, and a coordinator destination you control or have permission to use. A real routing test can transfer a call or send SMS. Set a small explicit budget and trial scope first. Use the earlier playbook for cost components, then check current provider pricing before spending; there is no fresh price quote in this handoff.

**Deliverable:** working test credentials stored locally, chosen voices/model, spending ceiling, and authorized test destinations. I can then run controlled checks and document results.

### Authorized data and reviewers

Start with invented calls and consenting volunteer roleplays. If you want historical enquiries, obtain an authorized export from the practice/agency or account owner; we cannot obtain private previous calls without access. Record source, permissions, retention, and permitted evaluation use. A call log is not an audio recording, and a recording is not an original live STT event stream.

Keep sensitive exports, recordings, and transcripts outside Git. Use restricted storage and an approved handling process. Ask an independent reviewer to label outcomes and review some recordings. A model evaluating itself is not sufficient evidence.

**Deliverable:** a permitted data source or a volunteer test plan, independent reviewer, and data-handling requirements. Import, de-identification, and audio archival tooling remain engineering tasks, not implemented capabilities.

## What I can continue implementing

You do not need to manually code the following backlog. These are engineering tasks I can take through further iterations once their policy/account dependencies are resolved.

| Priority | Work | Acceptance evidence |
|---|---|---|
| Before paid benchmarks | Complete a new reviewed prompt version and validate coverage; structural readiness guard is implemented | Placeholder or empty suites fail before vendor work; approved cases run |
| Before claiming reproducibility | Capture complete caller inputs and remaining remote/runtime provenance; compatibility rules for audio runs | Old/incomplete/mixed runs cannot receive a comparable-run verdict |
| Before real routing | Explicit consent evidence, atomic Postgres slot claiming, idempotency, callback timezone handling | Concurrent bookings cannot double-claim; retry cannot duplicate actions |
| Before claiming a handoff | Provider call status and coordinator-answer reconciliation, no-answer fallback | An accepted API request is distinguished from a person answering |
| Before latency claims | Speech-end and first-outbound-audio probes, provider first-token timing, clock definitions | Measured distributions with samples and documented timing boundaries |
| Before load rollout | Admission limits, concurrency tests, websocket disconnect/reconnect policy, graceful draining | Load/failure tests with bounded resource use and safe shutdown |
| Before live data | Retention verification, access/audit design, authorized import pipeline, backup/restore | Demonstrated deletion/restore and approved data flow |
| Before broader product access | Appropriate hosted authentication and tenant isolation if required | Cross-user/tenant access tests and trusted identity boundary |

The current audio client uses server-supplied transcript/extraction data for grading. It does not independently recognize the synthesized audio. Legacy `playback_start_ms` is a completion acknowledgement, not first audio heard; response latency stays unavailable rather than being fabricated. These limits still matter after configuration tracking.

## Practical sequence for you

### First: run the project locally and review fictional data

Commands below run from the nested repository directory, `Arcagent/arcagent`.

Use Python 3.12, which CI tests, or another supported version at least 3.11. Check that `python3` selects that interpreter. For a fresh checkout only:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,agent,dashboard]'
```

Use the existing `.venv` if it is already set up. Configure an ignored `.env` using `.env.example`; do not overwrite an existing file containing your settings. Then, with Docker available:

```bash
docker compose up -d
.venv/bin/alembic upgrade head
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

The Docker database uses a persistent named volume. The example database credentials are local-development defaults. Tests use fixtures and temporary databases and do not require paid vendor calls.

To inspect the website locally, follow `web/SETUP.md`. From `web/`, use the Node version in `package.json`, `npm ci`, then `npm run dev`. `/demo` stays fictional. `/workspace` is the connected view and needs its separate authorization/configuration.

### Second: complete prompts and personas, then establish the text baseline

Run the offline diagnostic first:

```bash
.venv/bin/python -m evals.preflight --prompts v1 --json
```

Current owner files intentionally produce exit `2`: seven placeholder prompts and no selected personas. After preparing reviewed files, select the new version and rerun. Exit `0` verifies structure only. Protected execution paths reject placeholders without a bypass flag. Restart the backend after prompt edits to clear cached text.

Do not proceed to model evaluation until the placeholder prompt and empty persona issues above are resolved. With reviewed inputs and credentials:

```bash
.venv/bin/python -m evals.run_text --run-name reviewed-text-baseline --repeats 3
```

Keep the run ID. Inspect failures and saved transcripts. Change one input at a time, then use `evals.compare_runs` for compatible text runs. A passing offline test suite says the harness behaves as tested; it does not say the model meets the benchmark.

### Third: run isolated synthetic audio

Use a dedicated test database and environment. Both evaluation server and harness must use the current protocol version and the same test database. Follow `VOICE_TESTING.md` for exact variables and commands. Required switches include `ENV=test`, `ENABLE_AUDIO_EVALS=true`, and a separate `AUDIO_EVAL_TOKEN`. These authorize simulation only.

Start with one reviewed scenario and inspect its stored evidence before broadening. Speech and model APIs still cost money. `--no-db` skips the evaluation-result write; it does not remove the server's call/turn persistence or the runner's database reads. Do not point this environment at production data.

**Exit criterion:** expected outcomes/fields are checked, failures are inspectable, configuration evidence is retained, and missing data does not silently pass.

### Fourth: controlled real-phone tests

After synthetic gates and real-routing prerequisites pass, expose the backend over trusted HTTPS/WSS and configure the Twilio inbound webhook to `POST /voice/inbound`. Set `PUBLIC_URL` to the public origin. Keep signature validation enabled, use test destinations, and follow the approved disclosure/data plan.

Use consenting volunteers and invented details first. Record what happened, including caller interruptions, actual coordinator answer/no-answer, SMS receipt, and any unexpected action. A temporary development tunnel can support supervised testing; it is not the finished deployment. Keep paid tests within the agreed budget.

### Fifth: stage, measure, and iterate

You do not need cloud resources for offline development, fixture tests, or a local database. Deploy a separate staging voice backend when you need a stable public webhook, remote collaborators, repeated real calls, or realistic operational validation. Continue iterating locally and promote reviewed changes to staging; do not wait for every feature to be finished, and do not use production patient data as the development environment.

Deploy the FastAPI voice service, a Postgres database, migrations, secrets, and the necessary scheduled operational jobs. The website is a separate deployment. The existing retention command is `.venv/bin/python -m scripts.purge_old_data --dry-run`; inspect its proposed deletions before scheduling a real purge, and verify the policy against your retention requirements. Audio/object storage is optional until an approved recording/import workflow requires it. The LLM/STT/TTS APIs are external services; you do not deploy those vendor models yourself in the current architecture.

To connect website records, set backend `CONSOLE_API_TOKEN`; set server-only website `ARCAGENT_API_URL`, matching `ARCAGENT_API_TOKEN`, and `ARCAGENT_ALLOWED_USER_IDS`. `ADMIN_API_TOKEN` is separate and does not belong in browser code. The current hosted identity design depends on Sites; moving hosts requires an appropriate identity integration. A private website does not imply that the voice backend is deployed or that data processing is approved.

**Exit criterion:** migrations, health checks, authenticated access, restart/deploy behavior during calls, restore, retention, and controlled call results are demonstrated in staging. Production is a separate decision after those gates.

## Evidence to retain for interviews and product decisions

Keep a short engineering report for each experiment: problem, hypothesis, baseline, exact inputs/configuration, change, scenario count, failures, latency definition, cost, and conclusion. Include unsuccessful experiments and what they taught you. Save reproducible failure cases and explain why each test catches a real risk.

A strong portfolio demonstration can show a synthetic call, its transcript/extracted fields, an independently expected outcome, an intentionally failing case, and the regression that prevented recurrence. Demonstrate tracing an interruption or no-answer failure rather than relying only on a polished demo. Do not present unmeasured latency, simulated bookings, or offline pass counts as real operational results.

## Immediate checklist

- [ ] Review this handoff and the scoring/conversation policies.
- [ ] Provide approved prompt wording or decisions for a new prompt version.
- [ ] Write and independently review runnable owner personas.
- [ ] Choose test vendor accounts, voices/model, destinations, and a spending cap.
- [ ] Configure secrets locally and a separate evaluation database.
- [ ] Run and inspect the reviewed text baseline before paying for audio runs.
- [ ] Arrange fictional volunteer calls and an independent reviewer.
- [ ] Decide staging access, region/data requirements, and budget when the controlled-call gates pass.

The next engineering work can continue without completing every checkbox. Credentials, approved data, real callers, and spending decisions are the points where your participation becomes necessary.


## Verification for this handoff

Final local suite: `592 passed, 1 skipped in 5.85s`. Ruff lint passed; formatting reported `125 files already formatted`; `git diff --check` passed. The tests exercise synthetic transport, controlled model/vendor boundaries, and temporary databases. They do not establish live latency, real vendor account access, or suitability for actual patient calls. See the GitHub Actions run for the pushed commit for backend and website CI status.


Latest readiness iteration: `614 passed, 1 skipped in 5.96s`; lint/formatting passed. The original owner prompt and persona gaps remain, but execution paths now reject them explicitly. Run the preflight command above to see the remaining input work without credentials or paid calls.


## Operations interface iteration

Added an Operations landing view to the workspace: authenticated configuration checks, recent call counts, abandoned/unfinished call review, prompt findings, and recovery guides. Fictional demo scenarios exercise setup and database-outage states. Counts remain unavailable when the database fails; frontend timeouts and malformed responses show explicit retry states. Requests never initiate calls, send messages, or retry ambiguous routing actions. A copyable report includes configuration information without transcript content.

The UI uses TypeScript, Tailwind v4, shadcn/Base UI, Lucide, Motion, and a selective Magic UI dot-pattern adaptation. Native Next.js scripts now coexist with the existing Vinext/Sites deployment. Use `npm run dev:next` from `web/` to explore the native demo. Native live records remain locked until a verified identity adapter is configured; incoming Sites-style headers are not trusted there. The existing Sites build preserves its trusted hosting boundary. See `web/SETUP.md` for commands and limitations.

Your next setup remains approved prompts/personas, credentials/budget, and controlled call validation. Configuration checks indicate presence, not vendor entitlement, reachability, or clinical suitability. The new page is not a monitoring service or an automatic incident-recovery system. This iteration updates repository source; it does not redeploy the previously published site.

Verification for this iteration: backend `619 passed, 1 skipped in 6.03s`; frontend `18 passed, 0 failed`. Ruff lint and formatting passed (`133 files already formatted`), frontend lint/typechecking passed, and both native Next.js and Sites production builds passed. Typechecking also passed after switching builds. Native production HTTP checks returned `200` for the demo and `401` for the console endpoint with forged Sites identity headers. Browser visual/interaction testing and live vendor calls were not performed. New dependencies are pinned `next@16.3.5` for native App Router support and `motion@13.4.0` for accessible transitions; no Python dependencies or migrations were added.

Next engineering priorities: implement and test a verified native session adapter before exposing live records outside Sites; add browser interaction coverage for refresh, failure review, keyboard navigation, and reduced motion; then measure real turn detection and playback latency with approved controlled calls. Keep the existing offline regressions as the promotion gate, and retain separate staging credentials and data. Native build output is isolated in `.next-native` so it does not collide with Sites output.

## Failure lab and human workflow implementation

### What now works

- **Failure experiments:** six deterministic synthetic scenarios cover silence, interruption, delayed transcripts, vendor timeout, disconnect, and unanswered handoff. Baseline and candidate policies produce ordered events/actions, fixed assertions, configuration provenance, and explicit differences. The CLI exits nonzero for mismatched assertions and refuses to overwrite an existing report. The authenticated UI supports custom comparisons; the public demo shows saved examples. This model reuses production scoring where relevant but does not execute the live audio state machine.
- **Actual integration evidence:** controlled tests run the production call session, graph responder, routing, persistence sink, and temporary database with external vendors replaced by fakes. They cover accepted transfer requests, transfer rejection with preserved lead/score and abandoned outcome, unavailable-coordinator callbacks, and disconnects without unintended routing.
- **Latency workbench:** each live call's timing view now reports stage-specific sample coverage, missing/invalid measurements, and nearest-rank percentiles. Analysis retains per-turn values. A pure paired-comparison interface rejects missing/mismatched provenance and duplicate turn keys. Ordinary live calls do not have sufficient experiment provenance for automatic paired comparison. Stage durations use different anchors and cannot be summed into caller-perceived latency.
- **Coordinator work:** authenticated users can create one follow-up per call, assign ownership, maintain notes, and mark work open/in-progress/resolved. Atomic audit history accompanies mutations. Revision checks prevent silent concurrent overwrites. These actions do not dial, send SMS, or alter callback bookings.
- **Feedback review:** an author writes a fictional reproduction and expected behavior; a different authenticated reviewer approves or rejects it. Approved candidates export for manual test authoring. UUID idempotency prevents duplicate creation for retries of the same intent. Changed payload or actor with a reused key is rejected. Human de-identification review remains required.
- **Staging preparation:** isolated PostgreSQL/backend Compose recipe, unprivileged read-only backend container, explicit migrations, and a bounded read-only verifier for authentication, readiness, and schema revision. Runbooks cover controlled calls, backup/restore, restart, and rollback. No infrastructure was provisioned.

### Failure behavior and upgrade instructions

Apply `alembic upgrade head` using the intended database configuration before opening the new live workflows. The new revision is `c21ab845df10`. Back up existing data first. Migration tests cover upgrade/downgrade and call-retention cascades; no local or remote user database was migrated during implementation. An old schema yields an unavailable-workspace response rather than fabricated successful writes.

The browser proxy allows only supported routes/methods, bounds request bodies, checks mutation origin, and overwrites actor headers from verified identity. Transactions commit before success is returned. Database and transport exceptions are sanitized. A lost save response is treated as uncertain, never automatically retried. Follow-ups deduplicate by call; feedback deduplicates by request UUID; updates/reviews require revisions. Refresh and reconcile records after uncertain results or conflicts. Drafts are only in memory, not durable browser storage. A full page reload loses unsaved drafts, so copy them before discarding a view.

Feature pages load on demand. Route rendering failures have a recovery screen. Latency-summary failures preserve access to the original turn measurements. Failed queue reads do not substitute fictional data.

### Critical remaining engineering work

1. **Answered-transfer semantics:** accepted Twilio transfer requests still do not confirm that a coordinator answered. Implement signed, idempotent transfer-result handling before treating handoffs as completed connections. Test no-answer, busy, failed, late/duplicate callbacks, caller disconnect, and ambiguous external completion. Only then add an automatic recovery task or consent-aware callback. The current follow-up queue is manually initiated; the synthetic unanswered scenario does not implement this production behavior.
2. **Real audio evidence:** run the controlled-call checklist in FAILURE_LAB.md with approved prompts, fictional details, owner-controlled destinations, and a spending cap. Measure speech-end-to-audible-response using appropriate timestamps/audio evidence. Tune turn detection only against repeated measured scenarios, including interruption and noise. Existing playback acknowledgement is completion, not first audible output.
3. **Replay depth:** the UI policy model is complemented by a standalone actual-session replay runner. It uses fixed versioned synthetic events and scripted dependencies. A future recorder must capture sanitized production events, preserve provenance, and define which external responses can be reused safely. Historical audio replay, changed-LLM qualification comparisons, and counterfactual live-call accuracy are not established by these fixtures.
4. **Reviewed feedback execution:** turn approved exports into independently checked executable scenarios and test code. Require meaningful expected outcomes and provenance, then include them in baseline/candidate eval comparisons. Approval alone does not create a runnable test.
5. **Deployment verification:** Docker is unavailable in the implementation environment. Build/run the recipe, exercise real PostgreSQL concurrency, restore a backup into an isolated database, and test restarts on the target platform. Pin dependency/base-image artifacts before production. Configure HTTPS ingress and observability. Keep one worker until process-local coordination is replaced or validated for scaling.
6. **Identity and browser testing:** Sites remains the supported identity boundary. Native Next live access stays closed pending a verified identity adapter. Exercise the UI in the browser for forms, keyboard navigation, reload/reconciliation, responsive layouts, and reduced motion before release. No browser interaction/visual test suite was run in this iteration.

### What you need to supply

Approve prompt wording and persona expectations; provide dedicated staging vendor accounts and destinations; choose a budget, hosting region, and backup policy; arrange an independent feedback reviewer and controlled-call tester. Use STAGING_RUNBOOK.md for exact commands and acceptance gates. Do not use real patient data to establish initial behavior. The source is ready for continued development, not a claim that production operation is break-proof.

### Actual-session replay addition

`python -m scripts.run_session_replay` executes interruption, disconnect, and synthesis-failure fixtures against the real `CallSession` with scripted dependencies. It records the production implementation source SHA256, fixture version, settings, observed output actions, and assertions. `--scenario interrupt --candidate-barge-in-min-words 4` demonstrates a real configuration-sensitive failure: the candidate ignores the fixture's three-word interruption and exits nonzero. The default three scenarios pass. No credentials, prompts, database, network, or vendor APIs are involved. A watchdog bounds execution; cleanup cancels and awaits session tasks. This CLI layer is separate from the UI's synthetic policy model.

Final local verification for this iteration: `690 passed, 1 skipped in 7.36s`; frontend `24 passed, 0 failed`; Ruff lint/format passed (`151 files already formatted`); frontend typecheck/lint and native Next/Sites production builds passed; `git diff --check` passed. Native demo HTTP smoke checks returned `200` for lab and workflow views. Both default offline lab CLIs pass; the deliberate actual-session interruption counterfactual exits `1`. No new dependencies. CI additionally builds the staging image; target-platform Compose/PostgreSQL/live-vendor verification remains separate. No user database migrations, cloud provisioning, real calls, SMS, or site redeployment were performed.
