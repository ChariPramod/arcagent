# Architecture

## The call path

```
Caller (PSTN)
   |
   v
Twilio Voice  --POST-->  /voice/inbound        signature validated, returns TwiML
   |                       <Connect><Stream url="wss://$PUBLIC_URL/voice/stream">
   |                       with <Parameter> carrying the call sid and caller number
   |
   |  bidirectional WebSocket, base64 mulaw 8 kHz, 20 ms frames
   v
/voice/stream  ->  CallSession                 one asyncio TaskGroup per call
   |
   +-- reader       Twilio frames  ->  Deepgram, and marks -> turn state
   +-- transcripts  Deepgram       ->  turn queue, barge in, language watch
   +-- agent        turn queue     ->  GraphResponder -> Cartesia -> outbound queue
   +-- writer       outbound queue ->  Twilio            THE ONLY AUDIO WRITER
   +-- silence      watchdog       ->  re-prompt, then goodbye
   |
   v
CallRouter                                     score, persist, then act
   |-- handoff:  Twilio REST call update with <Dial> to the coordinator
   +-- callback: book a slot, send the SMS with the opt out line
```

Audio is mulaw 8 kHz from the moment it leaves Twilio to the moment it returns. Deepgram
accepts mulaw directly and Cartesia emits it directly, so nothing in this repo resamples.

## Why raw Media Streams

Twilio offers a managed layer that would do STT and TTS for us. Using it would remove the
part of this system worth demonstrating: control over the vendors, the latency budget, and
the turn-taking. The tradeoff is that barge in, cancellation and framing become our
problem, which is why `docs/turn_taking.md` exists and why the barge in tests assert on the
order of operations rather than the outcome.

## Concurrency

Five tasks per call, listed above. One rule holds the design together: **the writer is the
only task that sends audio to Twilio.** Everything else queues. That is what makes "the
agent talked over itself" impossible rather than unlikely.

Cancellation is the hard part and it is tested, not assumed. Two bugs found by those tests
are recorded in `docs/failure_modes.md`.

## The agent

A LangGraph state machine, not a free-running model. The graph decides what to ask next;
the model decides how to phrase it. Five nodes call the model, five are pure functions.
Node responsibilities are in `docs/conversation_design.md`.

Each model call uses structured outputs against a schema that contains only the fields that
node owns, so one node cannot overwrite another's extraction. Calls are streamed, which is
the only way to measure time to first token, then parsed complete.

## Scoring

`arcagent/agent/scoring.py` is pure, deterministic and unit tested against the rule table in
`docs/scoring.md`. The model is never asked whether a lead is hot. That is what makes the
eval harness meaningful: identical extracted fields always produce an identical decision, so
a change in outcomes is always a change in extraction or conversation.

## Data

PostgreSQL. Eight tables, schema in `arcagent/persistence/models.py`, migrations in
`alembic/`. Two rules are in the schema rather than in a convention:

- `calls.from_number_hash` is a hash. The caller's real number exists only in `leads`.
- no audio is stored. Transcripts are, and they are subject to the retention config.

## Evaluation

Two tiers over one fixed persona set.

| | Tier 1 (`run_text`) | Tier 2 (`run_audio`) |
|---|---|---|
| Drives | the graph directly | the real WebSocket handler |
| Sees | extraction, routing, objection handling | STT errors, endpointing, barge in, latency |
| Cost | model calls only | model calls plus TTS |
| Speed | seconds per scenario | roughly real time |

Both write to `eval_runs` and `eval_results`, tagged with the git sha and the prompt
version. `compare_runs` diffs two runs and fails on a guarded regression.

## Deliberate omissions

- No echo cancellation. Twilio gives us the inbound track only.
- No custom VAD. Deepgram's endpointing does it, and the tradeoff is tuned there.
- No audio pacing in the writer. Twilio buffers and plays in real time; the mark tells us
  when playback finished.
- No retry on a failed warm transfer. The lead is saved first, so a human can pick it up.
