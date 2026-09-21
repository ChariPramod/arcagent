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
| Before paid benchmarks | Prompt readiness guard; complete a new reviewed prompt version; validate benchmark coverage | Placeholder or empty suites fail before vendor work; approved cases run |
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
