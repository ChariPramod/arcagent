# Operator workflow

The workspace supports a supervised dental-group pilot. Authorized staff share access to the group; location labels filter work and do not create location-level permissions. Demo records are fictional. Live calling, Google sign-in activation and vendor validation remain separate readiness requirements.

## Find an enquiry

Use the lead pipeline search to find a captured name, callback number or call ID across stored enquiries. Search is a literal, case-insensitive substring match on the latest saved lead's name and phone number. An ASCII digit-only query also matches that exact call ID. Formatting is literal: punctuation, spaces and country-code prefixes are not automatically normalized away.

Search terms are trimmed and normally contain 2 to 80 characters. A single ASCII digit from 1 to 9 is also accepted for an exact call-ID lookup; this exception does not enable broad single-character name or phone searches. Surrounding whitespace is stripped; remaining nonprintable characters are rejected. The browser sends the term in the JSON body of `POST /api/console/pipeline/search`; the term is not placed in the request URL or echoed in response metadata or validation errors. This does not make it anonymous: searching for a contact still involves sensitive data and must use authorized workspace access.

Location, follow-up timing and unassigned-owner filters apply together with search. Stage selection filters the displayed results and their total; the stage summary continues to describe all matching stages. Results remain paginated, so the first page is not a complete export of every match. Search is read-only and uses the same authentication boundary as the pipeline.

## Review a call's staff activity

The activity timeline brings pipeline edits, follow-up changes, feedback reviews and CRM delivery events together for one call. Entries show the staff actor or integration worker, recorded action, timestamp and revision. They do not prove that a patient was reached or that a person answered a transfer.

Operational changes such as stage, staff owner, location, next-action time and delivery status can be displayed. When a contact name, callback number, note, synthetic scenario or review evidence changed, the timeline names the changed field without copying its private value. Unknown metadata keys and unknown event entities are excluded. Invalid operational values are omitted instead of displaying arbitrary historical payloads.

The authenticated endpoint is `GET /api/console/calls/{call_id}/activity`. It defaults to 25 entries, accepts a limit from 1 to 100, and returns `has_more` plus `next_before`. Pass that audit ID as `before` to load older entries. Ordering uses descending audit IDs, so a newly inserted event does not duplicate or skip entries while loading older pages. Refresh to see newer events. Timestamps are display metadata rather than the pagination key.

The endpoint checks that the call exists and fetches only one page plus one row to detect more history. It does not count the entire audit history. An unknown call returns not found; an existing call with no matching events returns an empty timeline. Database errors return an unavailable response. This is a workflow timeline, not an audit of every sensitive-data read or a tamper-evident event store.

## Handle uncertain CRM delivery

A receiver can accept a request while its response is lost. The resulting `uncertain` status must not be treated as an invitation to send the contact again. Inspect the destination using the original delivery and contact context, then record a human review of what was found.

Review resolutions distinguish verified receipt, verified absence and a need for more follow-up. A review preserves the original provider status, attempt history and delivery snapshot. Human review is additional evidence, not a rewritten transport result. Review evidence is stored in the protected review record; the activity timeline shows the operational resolution without copying the evidence text.

The review request includes a submission UUID, the status and attempt count being reviewed, the current review revision, the chosen resolution and concise evidence. A repeated identical submission can recover a lost response without creating another review. A conflicting or stale submission requires refreshing the delivery before acting. Do not put credentials, full transcripts or unnecessary patient details in review evidence.

Stale delivery recovery is a separate explicit action. It marks an old interrupted `sending` claim as uncertain for inspection. It does not call a CRM, resend a contact or establish whether the receiver accepted the original attempt. Follow the normal destination verification process after recovery.

## Verification and limits

The activity endpoint has 13 focused passing tests covering authentication before database work, stable cursor paging with concurrent inserts, call isolation, empty and missing calls, bounded reads without a total count, allowlisted details, private-value omission, malformed metadata and sanitized database failures. No new runtime dependency is required for the timeline.

These features organize staff work and preserve evidence. They do not enable automatic outreach, guarantee an external application's delivery, or establish production readiness. The existing retention preview and operator-controlled text redaction are described in [Storage and query optimization](STORAGE_AND_QUERY_OPTIMIZATION.md).
