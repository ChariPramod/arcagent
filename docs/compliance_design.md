# Compliance design, and what is missing

This is a portfolio project. It is **not** HIPAA compliant and it is not deployed. What
follows is the design as if it were going to be, and an honest list of what a production
deployment would still need. The gaps are the interesting part.

## What is PHI here

A caller's name, phone number, and stated interest in a dental procedure, handled on behalf
of a covered entity, together constitute PHI. Transcripts and extracted fields are treated
that way throughout.

## Implemented

| Control | Where |
|---|---|
| Recording and AI disclosure on the first turn, spoken verbatim, non skippable | `prompts/v1/greeting.md`, spoken by `greet_and_disclose` with no model call so it cannot be paraphrased away |
| Caller number hashed at the door | `calls.from_number_hash`, `logging.hash_number` |
| PII redacted from every log line | `arcagent/logging.py`, tested in `tests/test_logging_redaction.py` |
| Transcript text never logged at INFO | same, `TRANSCRIPT_KEYS` are replaced with a length |
| No audio stored | nothing in the pipeline writes audio to disk |
| Webhook signature validation | `arcagent/telephony/security.py`, fails closed when the token is missing |
| TCPA consent evidence on the callback | `callbacks.consent_at` and `consent_turn_index` |
| Opt out line on every SMS | `twilio_actions.OPT_OUT_LINE`, asserted in tests |
| SMS content minimisation | the message names no person and nothing clinical, asserted in tests |
| Retention config | `TRANSCRIPT_RETENTION_DAYS`, default 30, with `scripts/purge_old_data.py` |

## Not implemented, and needed for production

1. **Business Associate Agreements.** Twilio, Deepgram and Cartesia each discuss BAAs for
   healthcare customers. None is executed here, and no vendor free tier may be used for
   anything described as production. This is the largest single gap.
2. **Encryption at rest for the leads table.** `callback_number` and `name` are stored in
   plain columns. A production deployment needs column level encryption or an encrypted
   volume with managed keys, plus a key rotation story.
3. **Access control.** There is no authentication on the dashboard or on
   `/admin/coordinator`. Anything that reads lead data needs authentication, authorisation
   and an audit log of who read what.
4. **All party consent by state.** Twelve US states require all party consent to record.
   The disclosure is spoken, but there is no per state routing and no evidence capture
   beyond the transcript. A production system needs to know which state the caller is in.
5. **Audit logging.** No record of who accessed a lead, when, or why.
6. **Data subject requests.** No mechanism to find and delete everything about one caller
   on request.
7. **Breach detection and response.** None.
8. **Vendor data residency and sub-processor review.** Not done.

## Retention

Transcripts and turns are deleted after `TRANSCRIPT_RETENTION_DAYS`, default 30, by
`scripts/purge_old_data.py`. The lead record survives, because that is the business record
the practice is entitled to keep; the conversation that produced it is not.

The purge is a script, not a managed job. A production deployment schedules it and alerts
when it does not run.

## What the agent is forbidden from doing

Enforced by prompt and, where it matters, by the graph:

- never quote a price
- never give clinical advice or say whether the caller is a candidate
- never claim to be a person; answer plainly every time it is asked
- never promise insurance coverage; it extracts the signal, it does not verify a plan
- stop qualifying a caller who says they are under 18 and ask for a parent or guardian

The last one is a graph path, not a prompt instruction, because a prompt instruction can be
argued with. See `arcagent/agent/edge_cases.py`.

## Honest summary

If a practice wanted to run this, the work between here and there is not the voice pipeline.
It is BAAs, encryption, access control, audit, and a per state consent model. The pipeline is
the easy part, and saying otherwise would be the dishonest version of this document.
