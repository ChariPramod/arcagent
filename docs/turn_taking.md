# Turn taking, barge in, and silence

Written before the code, because concurrent cancellation is the part of this system most
likely to be plausible and wrong. The implementation is `arcagent/telephony/call_session.py`
and the tests that hold it to this document are `tests/test_barge_in.py`.

## Tasks

One `asyncio.TaskGroup` per call owns the transport and conversation loops. The agent
loop also owns a cancellable reply task.

| Task | Reads | Writes |
|---|---|---|
| `reader` | Twilio WebSocket | Deepgram socket, session state, silence timer |
| `transcripts` | Deepgram events | turn queue, session state |
| `agent` | turn queue | outbound audio queue |
| `writer` | outbound audio queue | Twilio WebSocket |
| `silence` | session activity and state | reprompt and goodbye requests |

`writer` is the only task that writes audio to Twilio. Nothing else may call `send_json`
with a media frame. This is the single property that makes "the agent talked over itself"
impossible rather than unlikely.

## States

The session is in exactly one of these:

- `LISTENING`: no agent audio outstanding. Caller speech accumulates.
- `SPEAKING`: the agent has audio queued or playing. `pending_marks` is non empty.
- `ENDING`: a terminal path has run. No new turns are accepted.

Transitions:

```
LISTENING --caller final transcript--> LISTENING (agent turn starts, becomes SPEAKING when
                                                 the first frame is queued)
SPEAKING  --mark for the last utterance--> LISTENING
SPEAKING  --barge in--> LISTENING
any       --stop event, hangup, or terminal node--> ENDING
```

## Barge in

While `SPEAKING`, a caller transcript triggers barge in when **either**:

- it is final, or
- it is interim and has at least `BARGE_IN_MIN_WORDS` words (default 3)

An interim transcript shorter than that is a backchannel. "uh huh", "okay", "right" do not
interrupt the agent, because callers say them while listening and cutting the agent off
every time reads as broken.

The barge in sequence, in this order, and the order matters:

1. Set state to `LISTENING` and take the current utterance's `context_id`. From this point
   the writer will discard anything it pulls for that context.
2. Drain the outbound queue. Anything still queued is for the abandoned utterance.
3. Send Twilio `clear`. This discards audio Twilio has buffered but not yet played.
   Sending `clear` before draining would let the writer push more frames in behind it.
4. Clear `pending_marks`. Twilio returns marks for cleared audio too. Playback ownership
   is invalidated before sending `clear`, so these returned marks cannot certify playback.
5. Cancel the agent task, which cancels the LLM call and the TTS stream inside it.
6. Tell Cartesia to cancel the context. Best effort, saves billed characters, and the
   correctness of steps 1 to 5 does not depend on it landing.
7. Record each pending utterance once with `interrupted=True` and its generated text.
   This is not a transcript of the exact spoken prefix; that requires audio alignment.
8. Start the new turn from the caller transcript that caused the interruption.

The abandoned `context_id` stays in a `discarded` set for the rest of the call. Late chunks
for it are dropped by the writer rather than played.

## Silence

Caller transcripts reset the timer. Successful playback also resets the listening window.
Inbound media alone does not establish that a caller spoke.

- `SILENCE_REPROMPT_S` (default 8) with no caller transcript while `LISTENING`: speak one
  re-prompt. Only once per call.
- `SILENCE_HANGUP_S` (default 15) with no caller transcript: speak a goodbye line and end
  the call with outcome `abandoned`.

The timer does not run while `SPEAKING`. A caller listening to a long agent utterance is
not a silent caller.

## What is deliberately not done

- No echo cancellation. Twilio gives us the inbound track only, so the agent never hears
  itself and does not need it.
- No custom VAD. Deepgram's `endpointing` and `utterance_end_ms` do this, and the tradeoff
  between cutting people off and feeling slow is tuned there, not in our code.
- No audio pacing in the writer. Twilio buffers and plays in real time; the `mark`
  acknowledgement is what tells us playback finished.
