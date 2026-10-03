# Dental group pilot: two-day implementation and acceptance plan

## Offer and boundary

Offer a supervised enquiry follow-up pilot for one dental group with multiple locations. The practical demonstration is: capture an enquiry, assign its location and owner, record the next action, send a deliberate CRM delivery, and reconcile the result. The voice agent is an optional additional acceptance gate until approved prompts, credentials, destinations, and controlled call evidence exist.

Sell the defined pilot scope and implementation work, not a promise of recovered revenue, autonomous clinical advice, guaranteed bookings, or production reliability. Booked and won are operator-entered workflow stages. They do not establish that a practice management system accepted an appointment or that payment occurred. No commercial agreement, outreach, billing, or patient messaging is performed by this implementation.

The workspace serves one group. Authorized members share access across its locations. Location assignment and filtering organize work; they are not authorization boundaries or separate tenants. Do not onboard unrelated businesses into this database or promise branch-restricted access. That requires independently designed and tested tenant and location authorization.

## Day one: configure and prove the supervised workflow

1. Confirm the sponsor, group locations, operator, independent reviewer, pilot destinations, and data owner. Choose the exact CRM or automation receiver and agree who handles uncertain deliveries. Record a spending cap before using billed voice services.
2. Deploy the reviewed backend migration and website build to staging. Verify database health and authenticated console access. Configure native OIDC registration and exact redirect origin, session secret, and member allowlist using the setup runbook. A working fictional demo is not evidence of this connection.
3. Create the group's locations with reviewed names and time zones. Assign fictional enquiries to different locations; verify location filters, unassigned enquiries, ownership, next-action times, revision conflicts, and audit history. Include an enquiry without an existing pipeline record.
4. Configure one supported CRM destination in server secrets. Check its permissions and receiver contract using an owner-controlled test account. Make a deliberate delivery with fictional information and verify the resulting record at the destination. A configured credential or HTTP acceptance alone is not evidence that a follow-up task reached the intended operator.
5. Demonstrate the entire journey to the sponsor with fictional data: enquiry, location, assignee, next action, CRM result, and exception review. Record what is implemented and what depends on the receiver. Do not promise a native appointment-booking integration unless it is actually tested.

Day-one acceptance: an authorized operator can locate the right enquiry, assign a branch and owner, save a next action, and inspect a verified test delivery. Unauthorized API access is rejected. No credentials or contact data appear in readiness responses or operational logs.

## Day two: prove failures, recovery, and handoff

1. Submit the same delivery intent again and verify no duplicate external action. Simulate an interrupted or timed-out send. The result must remain uncertain until an operator compares it with the destination, rather than automatically retrying a potentially completed action.
2. Exercise database unavailability, invalid integration configuration, provider rejection, stale revisions, and concurrent edits. Preserve existing data and display explicit unavailable/uncertain states. Confirm the documented worker or dispatch command and its scheduling before promising automatic follow-up execution.
3. Verify that missing location assignment is visible. Deactivate a location and confirm historical records remain understandable. Test ownership and next-action work independently of call qualification: a high score is not a CRM completion or booking.
4. If approved voice inputs and vendor accounts are available, conduct controlled calls using fictional identities and owner-controlled destinations. Test an answered bridge, no answer, busy/rejected transfer, caller disconnect, interruption, and an ambiguous external response. Retain call and transfer identifiers in restricted evidence, with per-turn latency measurements and reviewer notes.
5. Run the regression suite, verify migrations on the staging database, and perform a backup/restore exercise in an isolated target before accepting live patient data. Review the pilot's access, retention, support contact, spending limit, and rollback procedure with the owner.

Day-two acceptance: the reviewer can explain one successful journey and one failed journey from persisted evidence, including whether the destination received a record and who owns recovery. Any unmet gate remains an explicit blocker, not an assumed pass. If credentials or external setup are unavailable, deliver a reproducible supervised demonstration and report the blocked live acceptance steps.

## Readiness view semantics

`GET /api/console/pilot` uses the existing console bearer authentication and returns no caller names, transcripts, contact numbers, credentials, or integration URLs. It reuses the existing operation configuration checks and summarizes the location and CRM backlog.

- Active locations are actual configured active rows, not invented branches.
- Unassigned leads count distinct stored enquiry call IDs with no location, including missing pipeline rows. Imported duplicate lead rows do not multiply the enquiry count. Test records are included; no production-only provenance filter is claimed.
- Pending CRM deliveries include queued and sending rows. Uncertain deliveries remain separate and require reconciliation.
- Counts cover the stored backlog, not a revenue or conversion estimate. Database failure produces unavailable counts rather than zeros.
- Configuration readiness establishes prerequisites only. Live vendor validation, website identity validation, and controlled pilot acceptance remain separate. This endpoint performs no paid probes, sends, calls, or credential validation.

## Owner work that code cannot substitute for

- Approve the conversation policy, new prompt wording, and independently reviewed personas. Existing owner-authored prompts remain protected, and placeholder readiness checks remain enforced.
- Configure the identity provider and authorize the exact staff account IDs. Local logout removes a browser cookie; stateless sessions may remain usable until expiry if copied. Remove a member from the allowlist to deny subsequent workspace access.
- Supply dedicated vendor and CRM credentials, approve destinations and access scopes, and determine the permitted data fields. Keep these in secret storage rather than repository files, browser state, or documents.
- Choose the group pilot operator and reviewer. Verify actual CRM records and any follow-up automations in the destination account. A connector cannot certify the receiver's internal workflow.
- Authorize billed tests and arrange controlled callers. Measure real latency instead of using offline test duration as a substitute.
- Confirm the operational data requirements, retention, backup ownership, and support arrangement before admitting real patient enquiries.

## Demonstration script

Show a fictional enquiry arriving in the shared group workspace. Assign the correct location, assign an operator, and schedule the next action. Save with the current revision. Request a CRM delivery and inspect its durable receipt. Then show an uncertain delivery: explain why it is not automatically resent, inspect the destination, and demonstrate the documented reconciliation process. Finally, show a no-answer transfer and its recovery task if controlled voice testing has passed.

The closing statement should be factual: “This pilot makes enquiry ownership and follow-up status visible across your group, with explicit handling when a handoff or delivery cannot be confirmed.” Attach the acceptance evidence and unresolved gates. Do not attach fabricated ROI figures or describe the system as break-proof.
