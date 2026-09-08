# Conversation design

> **Owner authored.** The node list is transcribed from section 3.5 of the scope document.
> `arcagent/agent/graph.py` implements it. The prompt wording in
> `arcagent/agent/prompts/v1/` is owner authored and currently placeholder.

The LLM's freedom is in phrasing, not in what to ask next. The graph decides the flow, so
the flow can be tested. That is the whole reason the eval harness means anything.

## Nodes

| # | Node | LLM | Owns | Leaves with |
|---|---|---|---|---|
| 1 | `greet_and_disclose` | no | the recording and AI disclosure | the caller knowing what they are talking to |
| 2 | `confirm_treatment_interest` | yes | `treatment_interest` | one of the six treatment values |
| 3 | `assess_situation` | yes | `missing_teeth_count`, `pain_level`, `considering_duration` | urgency signals |
| 4 | `extract_insurance_signal` | yes | `has_insurance`, `employer_name`, `plan_type`, `coverage_awareness` | the insurance picture |
| 5 | `handle_objection` | yes | marks an objection recovered or not | back to the node it came from |
| 6 | `capture_contact` | yes | `name`, `callback_number`, `preferred_time` | a reachable lead |
| 7 | `score_and_route` | no | nothing, it reads | a decision from `scoring.py` |
| 8 | `warm_transfer` or `book_callback_and_sms` | no | the routing side effect | a completed action |
| 9 | `end_call` | no | the outcome | a closed call |

`greet_and_disclose`, `score_and_route`, `warm_transfer`, `book_callback_and_sms` and
`end_call` are pure functions. They contain no LLM call, which means their behaviour is
identical on every run and the harness can hold them to it.

## Flow

```
greet_and_disclose
   |
   v
confirm_treatment_interest --wrong_number--> end_call
   |
   v
assess_situation
   |
   v
extract_insurance_signal
   |
   v
capture_contact
   |
   v
score_and_route --handoff--> warm_transfer --> end_call
   |
   +----------- callback --> book_callback_and_sms --> end_call
```

The objection detector runs after every caller turn from any node. When it fires, the graph
enters `handle_objection` and returns to the node it interrupted. The interrupted node is
kept in `return_to`, so an objection never loses the caller's place in the conversation.

## Objection playbook

| Objection | The agent's job | Recovered when |
|---|---|---|
| `price` | Do not quote a number. Name the range the practice works in only if the prompt says to, then move to financing. | the caller keeps talking about treatment |
| `fear` | Acknowledge, do not argue, offer the consultation as the low commitment next step. | the caller accepts a next step |
| `just_looking` | Do not push. Offer the callback once. | the caller accepts the callback |
| `spouse` | Offer a callback at a time when both can be on the phone. | the caller gives a time |
| `bad_experience` | Acknowledge specifically, do not diagnose or blame the other practice. | the caller continues |

A recovered objection scores nothing. An unrecovered price objection is a penalty. See
docs/scoring.md rule 8.

## What the agent must never do

- Quote a price for treatment. It does not have one, and a wrong number costs the practice
  the appointment.
- Give clinical or medical advice, including whether the caller is a candidate.
- Continue qualifying a caller who says they are under 18. Ask for a parent or guardian and
  end the qualification.
- Claim to be a person. If asked whether it is a robot, say plainly that it is an automated
  assistant, every time it is asked.
- Promise insurance coverage. It extracts the signal; it does not verify a plan.

## Structured output per node

Each LLM node returns exactly the fields it owns, plus `next_utterance`. Fields it does not
own are absent from its schema, so one node cannot overwrite another's extraction. A field
the caller has not answered comes back null, and null never overwrites a value already in
state.

## Prompt versioning

Prompts live in `arcagent/agent/prompts/v<N>/<node>.md`. A prompt change is a new version
directory, never an edit to an old one, so an eval run tagged `prompt_version=v1` can always
be reproduced.
