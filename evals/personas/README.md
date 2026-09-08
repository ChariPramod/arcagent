# Personas

**Owner authored. The agent must never write a file in this directory.**

Thirty YAML files, one per scenario. The agent cannot write these well, and if the same
author writes both the personas and the agent the eval measures nothing: it measures
whether a model agrees with itself. What the harness does measure is consistency and
regression, and the README says so.

`_template.yaml` is the schema. `evals/persona.py` validates every file against it and
fails loudly rather than silently skipping a malformed one.

## The thirty, from scope section 7.1

Group them so metrics can be broken down by category.

### hot_buyers (6)
- [ ] full arch, has insurance, names the employer
- [ ] full arch, self pay, asks about financing
- [ ] multiple implants, in pain
- [ ] single implant, has insurance
- [ ] referred by a friend who had it done
- [ ] returning caller who already had a consult elsewhere

### price_objectors (6)
- [ ] asks for a price in the first 20 seconds
- [ ] "I heard it's $30,000"
- [ ] wants a price before giving any information
- [ ] price objection, then recovers when financing is mentioned
- [ ] price objection, then hangs up
- [ ] asks whether insurance covers everything

### fear_hesitation (5)
- [ ] afraid of surgery
- [ ] bad experience at another dentist
- [ ] "I just want information"
- [ ] needs to talk to their spouse
- [ ] asks clinical questions the agent must not answer

### logistics (8)
- [ ] wrong number
- [ ] existing patient asking about an appointment
- [ ] Spanish speaker
- [ ] heavy background noise (tier 2 only)
- [ ] interrupts constantly
- [ ] goes silent mid call
- [ ] gives a different callback number than the caller ID
- [ ] refuses to give a name

### adversarial (5)
- [ ] tries to get the agent to quote a price
- [ ] tries to get medical advice
- [ ] asks if it is a robot, repeatedly
- [ ] gives contradictory information (single implant, then full arch)
- [ ] says they are 16 years old

## Writing them well

Real callers are terse and evasive. They do not volunteer their employer's name, they
answer a different question than the one asked, and they say "I don't know" to things they
do know. A persona that answers every question fully and in order will make the agent look
far better than it is.

Put what the caller **will not say unless pushed** in `withholds`. That field is what
separates a harness that measures extraction from one that measures politeness.

Before trusting a run, read five simulator transcripts end to end and ask whether a real
person sounds like that. If not, tighten the persona, not the agent.
