# Failure modes

Every failure found, what caused it, and what was done. The ones found by tests are here
already. The ones found on real calls are the owner's to add, with a timestamp and a call
sid, as they happen.

The scope calls for at least ten documented failures before shipping. Four are recorded so
far, all found by tests. Six or more will come from real calls, which is the point: a
failure found by a test was a design mistake, and a failure found on a call was a
misunderstanding of what a real caller does.

---

## Found by tests

### 1. A reconnecting STT socket retried forever

**Symptom.** The test suite hung. `DeepgramSTT` never gave up on a socket that connected
and immediately closed.

**Cause.** The reconnect attempt counter was reset on a successful *connect*. A socket that
accepted the connection and then died reset the counter every time, so `max_reconnects` was
never reached.

**Fix.** The counter resets on a successful `recv`, not a successful connect. A socket that
reconnects and immediately dies now backs off and eventually gives up.
`tests/test_deepgram_stt.py::TestReconnect::test_reconnect_attempts_are_bounded`.

### 2. A hangup mid utterance never ended the call

**Symptom.** Ending a call while the agent was speaking left the session running. In the
tests it looked like a two second delay in teardown; on a real call it would be a leaked
task per call and a stream that never closed.

**Cause.** asyncio delivers a cancellation to the task being *awaited*, not to the awaiting
task. Cancelling the agent loop while it awaited a turn task cancelled the turn task
instead, which looked identical to a barge in, so the loop swallowed it and started the
next turn.

**Fix.** The agent loop distinguishes the two by checking whether the call is ending, and
re-raises when it is. `tests/test_barge_in.py::TestShutdown`.

**Lesson.** This is the class of bug the plan warned about: plausible async code with a
race. It was found only because the test harness asserted on shutdown time rather than
tolerating it.

### 3. The silence goodbye was never spoken

**Symptom.** After 15 seconds of silence the call ended with no goodbye, despite the code
appearing to queue one.

**Cause.** The watchdog queued the goodbye and then called `end()` in the next statement.
`end()` cancels every task, including the writer, before a single frame reached Twilio.

**Fix.** The watchdog queues the goodbye and returns; the agent loop ends the call after the
goodbye has actually been spoken, in a `finally` so a synthesis failure cannot leave a
silent call open forever.

### 4. The re-prompt and the greeting were indistinguishable

**Symptom.** A responder could not tell "the call just started, greet the caller" from "the
caller has gone quiet, prompt them", because both arrived as an empty transcript.

**Cause.** Reusing the empty string as a signal for two different events.

**Fix.** The session's own utterances are sentinels compared by identity, each mapping to a
line spoken verbatim. A caller cannot trigger one by saying it, which is asserted in
`tests/test_barge_in.py::TestSilenceLines`.

---

## Found on real calls

TODO_OWNER. One entry per failure, with the call sid and the timestamp, in this shape:

### N. One line symptom

**Symptom.** What you heard, with the call sid and the time in the call.

**Cause.** What actually caused it, after reproducing it. Not the first guess.

**Fix.** What changed, and the regression test if one was feasible.
