# Lead scoring

> **Owner authored.** The rule table below is transcribed from section 3.6 of the scope
> document. `arcagent/agent/scoring.py` implements exactly this and its docstring reproduces
> the table. Change the table here first, then the code, then the tests.

The LLM never decides whether a lead is hot. It extracts fields; this table turns fields
into a number, and the number plus coordinator availability decides the route. That is what
makes the eval harness meaningful: the same extracted fields always produce the same
decision, so a change in outcomes is always a change in extraction or conversation, never
a change of mood.

## Rule table

| # | Signal | Field condition | Points |
|---|---|---|---|
| 1 | Treatment interest is full arch or multiple implants | `treatment_interest in {full_arch, multiple_implants}` | +30 |
| 2 | Treatment interest is single implant | `treatment_interest == single_implant` | +15 |
| 3 | Pain level 6 or higher | `pain_level >= 6` | +20 |
| 4 | Considering for more than 6 months | `considering_duration == over_6_months` | +10 |
| 5 | Has dental insurance, any plan | `has_insurance is True` | +15 |
| 6 | Named an employer or a plan | `employer_name` or `plan_type` is present | +10 |
| 7 | Asked about financing, not just price | `financing_asked is True` | +10 |
| 8 | Price objection raised and not recovered | a `price` objection with `recovered` false | -15 |
| 9 | Just looking, and declined the callback | a `just_looking` objection and `callback_declined` | -30 |

Rules 1 and 2 are mutually exclusive: the treatment interest is one value, so at most one
of them fires.

## Decision

```
handoff  if score >= HANDOFF_THRESHOLD and coordinator_available
callback otherwise
```

`HANDOFF_THRESHOLD` defaults to 60 and is a config value so the harness can sweep it. A
score at exactly the threshold is a handoff; the comparison is `>=`.

A lead with no coordinator available is never handed off, whatever it scores. Transferring
a hot caller into a phone that nobody answers is worse than booking them a callback.

## Why these weights

- Full arch is the treatment that pays for the ad spend, so it dominates the table.
- Pain is the strongest urgency signal a caller gives without being asked to rate their
  intent, which they would answer dishonestly.
- Insurance presence matters more than insurance detail, because implants are usually not
  covered anyway. The signal is that the caller is an organised buyer, not that the plan
  will pay.
- Asking about financing is a buying question. Asking about price is not; a price question
  is scored nowhere, and an unrecovered price objection is a penalty.
- The `just_looking` penalty is large enough on its own to keep a browser below the
  threshold even with a full arch interest, which is the intended behaviour.

## Field vocabularies

| Field | Values |
|---|---|
| `treatment_interest` | `full_arch`, `multiple_implants`, `single_implant`, `consultation_only`, `not_sure`, `wrong_number` |
| `considering_duration` | `under_1_month`, `one_to_6_months`, `over_6_months`, `unknown` |
| `coverage_awareness` | `knows_not_covered`, `thinks_covered`, `unsure` |
| objection `kind` | `price`, `fear`, `just_looking`, `spouse`, `bad_experience` |

`coverage_awareness` is extracted and stored but scores nothing. It is there for the
conversation, and for a later version of this table once there is data on whether it
predicts anything.

## Worked examples

| Scenario | Rules fired | Score | Decision at threshold 60 |
|---|---|---|---|
| Full arch, pain 8, insured, named employer | 1, 3, 5, 6 | 75 | handoff |
| Single implant, no pain, insured, asked about financing | 2, 5, 7 | 40 | callback |
| Full arch, insured, named employer, unrecovered price objection | 1, 5, 6, 8 | 40 | callback |
| Full arch, pain 7, insured, just looking and declined callback | 1, 3, 5, 9 | 35 | callback |
| Full arch, pain 6, insured | 1, 3, 5 | 65 | handoff, or callback if no coordinator |
