# Compliance design, and what is missing

This project has a staging deployment using synthetic data. It has not established
production healthcare compliance or completed real-call acceptance. Infrastructure and
application controls are not a compliance certification. See [architecture](architecture.md)
and [current activation evidence](../PROJECT_HANDOFF.md) for implemented access controls
and the remaining deployment gates. The checklist below still requires an owner-led
policy and legal review before handling real patient data.

## What is PHI here

A caller's name, phone number, and stated interest in a dental procedure, handled on behalf
of a covered entity, together constitute PHI. Transcripts and extracted fields are treated
that way throughout.

## Implemented

| Control | Where |
|---|---|
| Recording and AI disclosure on the first turn, spoken verbatim, non skippable | `prompts/v1/greeting.md`, spoken by `greet_and_disclose` with no model call so it cannot be paraphrased away |
| Caller number hashed at the door | `calls.from_number_hash`, `logging.hash_number` |
| Application log redaction filters | `arcagent/logging.py`, tested in `tests/test_logging_redaction.py` |
| Transcript text never logged at INFO | same, `TRANSCRIPT_KEYS` are replaced with a length |
| No live-session audio recording persisted by the application | evaluation artifacts and vendor storage require separate review |
| Webhook signature validation | `arcagent/telephony/security.py`, fails closed when the token is missing |
| TCPA consent evidence on the callback | `callbacks.consent_at` and `consent_turn_index` |
| Opt out line on every SMS | `twilio_actions.OPT_OUT_LINE`, asserted in tests |
| SMS content minimisation | the message names no person and nothing clinical, asserted in tests |
| Retention config | `TRANSCRIPT_RETENTION_DAYS`, with preview-first `scripts/purge_old_data.py` |

## Remaining production review

- **Vendor agreements and processing terms.** Execution and approval of the required
  agreements are not established by this repository. Provider account configuration,
  permitted data use, residency, and subprocessors require owner review.
- **Stored-data protection.** Lead contact fields and export snapshots are ordinary
  application columns, without application-level field encryption. Review infrastructure
  encryption, access grants, backup protection, and key rotation separately; the schema
  alone does not establish the deployed security policy.
- **Access control activation and scope.** Native OIDC sessions, an operator allowlist,
  and the server-only console proxy are implemented. Console endpoints authenticate a
  dedicated bearer credential. Both read and write `/admin/coordinator` routes require
  the separate administrative credential. See [routes](../arcagent/app.py),
  [administrative authentication](../arcagent/telephony/security.py), and
  [workspace proxy](../web/lib/proxy.ts). Google client registration and approved
  operators remain activation steps. The legacy local Streamlit dashboard does not
  implement its own authentication and should not be assumed protected by the Next.js
  session. Location filtering is not independent tenant isolation.
- **Consent and disclosure review.** Callback consent fields and the disclosure path
  exist, but approved prompt content and an applicable consent policy remain owner
  inputs. Their existence does not establish legal sufficiency or consent for unrelated
  uses of stored data.
- **Audit coverage.** Staff workflow mutations and integration attempts record actors
  and changes in [workflow audit records](../arcagent/persistence/workflow_models.py).
  This is not a comprehensive record of every lead read, access purpose, database
  administrator action, or external provider operation.
- **Data access and deletion requests.** Transcript redaction is implemented below;
  a complete caller-level export/deletion workflow across extracted data, snapshots,
  backups, evaluations, and vendors is not established.
- **Incident response and recovery.** An exercised response process, access review,
  and target-platform backup/restore evidence remain acceptance work. Unit tests and
  synthetic staging writes do not substitute for those operational checks.

## Retention

The [retention command](../scripts/purge_old_data.py) previews eligible transcript text by
default. Explicit `--apply` redacts nonempty turn text for completed calls whose end time
precedes the configured `TRANSCRIPT_RETENTION_DAYS` cutoff. It records
`transcript_redacted_at` while preserving turn rows, latency evidence, calls, leads,
workflow audits, and delivery/idempotency records. Bounded batches commit independently
and can resume after interruption.

This operation does not erase extracted fields, contact export snapshots, evaluation
transcripts, backups, or copies held by vendors. Preserving a record technically does not
establish a legal entitlement to retain it. The owner must approve separate lifecycle
policies for those data categories, including access and deletion requests.

The command is not scheduled automatically. Operators must inspect its preview before
applying it, arrange scheduling and failure alerts when approved, and verify backup and
vendor retention separately. The [storage preview API](../arcagent/console/storage.py)
reports bounded application-level candidates without transcript content; it does not
claim physical disk space reclamation.

## What the agent is forbidden from doing

Enforced by prompt and, where it matters, by the graph:

- never quote a price
- never give clinical advice or say whether the caller is a candidate
- never claim to be a person; answer plainly every time it is asked
- never promise insurance coverage; it extracts the signal, it does not verify a plan
- stop qualifying a caller who says they are under 18 and ask for a parent or guardian

The last one is a graph path, not a prompt instruction, because a prompt instruction can be
argued with. See `arcagent/agent/edge_cases.py`.

## Acceptance boundary

Production use still requires approved content and data policies, activated identity and
provider configuration, controlled calls, measured behavior under failure, and reviewed
operational safeguards. The implemented voice pipeline and workspace provide a basis for
those checks; they do not establish compliance or production readiness by themselves.
