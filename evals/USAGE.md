# Reproducible text evaluations

For authenticated synthetic audio transport, isolation requirements, and measurement
limitations, see [Controlled voice testing](../VOICE_TESTING.md).

Apply database migrations before writing new evaluations:

```bash
alembic upgrade head
python -m evals.run_text --run-name baseline
```

Text runs capture the loaded personas, effective prompt text and hashes, agent and caller
model names, execution settings, source hashes and runtime versions before calling the
models. Only explicitly selected settings are saved; environment credentials are excluded.
The recorded inputs make runs inspectable. Model sampling and vendor model changes can
still produce different outputs from the same inputs.

Export an existing run's inputs for review:

```bash
python -m evals.snapshots RUN_ID --output inputs.json
```

## Comparing runs

```bash
python -m evals.compare_runs OLD_RUN_ID NEW_RUN_ID
```

The exit status is zero for no guarded regression, one for a regression, and two when
evidence is missing or incompatible. A comparison needs complete, unique scenario/repeat
coverage, valid measurements, and all categories named in the regression guards. Guarded
handoff recall also needs expected handoffs in that category.

Both runs must use the same personas, expectations, caller instructions, caller model,
repeat count, coordinator availability and suite. Prompt, agent model and threshold changes
are allowed and reported. Editing persona files on disk does not change a historical
comparison or its category labels.

Historical runs have no snapshot and must be rerun for a merge verdict. There is no inferred
backfill from today's files. Audio evaluations do not yet record the remote server's input
configuration or qualification metrics and cannot produce this text qualification verdict.

## Synthetic delivery mutations

```bash
python -m evals.mutations --list
python -m evals.mutations --run-name delivery-baseline
python -m evals.mutations --run-name delivery-experiment --no-db
```

Listing is offline. Evaluation uses the configured LLM and requires its credentials. Each
synthetic fixture has a baseline, hesitations, spacing changes, irrelevant details and an
explicit self-correction. Each variant is scored against the fixture's expected fields and
outcome, so consistently wrong answers still fail. The command exits unsuccessfully if any
case fails. Transcripts and exact caller scripts are saved with the run unless `--no-db` is
used.

These callers follow fixed scripts regardless of what the agent asks. They test delivery
robustness, not conversational realism. They use the `fixture_mutations` suite and cannot be
compared with the `owner_personas` benchmark. The fixtures live under `evals/fixtures/`;
owner-authored personas and prompts are not changed by this workflow.

Offline tests use fake model outputs to verify the harness and failure reporting. Passing
those tests is not evidence of model extraction quality or performance on real callers.
