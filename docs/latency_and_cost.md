# Latency and cost

Every number in this document is measured or it is marked `TODO_OWNER`. Nothing here is an
estimate presented as a measurement.

## The budget

Callers hang up on dead air. The target is under 800 ms from the end of the caller's speech
to the first agent audio on the wire.

| Stage | Target | Column | How it is measured |
|---|---|---|---|
| Deepgram endpoint detection | 200 to 300 ms | `turns.stt_final_ms` | final transcript timestamp minus the last inbound audio frame |
| LLM time to first token | 200 to 400 ms | `turns.llm_ttft_ms` | first streamed token minus request sent |
| Cartesia first audio byte | under 150 ms | `turns.tts_first_byte_ms` | first audio chunk minus synthesis requested |
| Twilio playback start | under 100 ms | `turns.playback_start_ms` | first `mark` event minus the first frame written |

All four are written on every turn by `arcagent/telephony/latency.py`. A stage that did not
run stores null, not zero, because a missing measurement is not a fast one.

## Measured

TODO_OWNER: run the audio harness and paste the table.

    python -m evals.run_audio --run-name latency-baseline --groups hot_buyers --n 3

The p50 and p95 per stage come out of that run and are also visible per call in the
dashboard. Do not fill this in from the tier 1 harness: tier 1 has no audio path and its
numbers would be a different measurement wearing this table's label.

| Stage | p50 | p95 | n |
|---|---|---|---|
| stt_final_ms | TODO_OWNER | TODO_OWNER | |
| llm_ttft_ms | TODO_OWNER | TODO_OWNER | |
| tts_first_byte_ms | TODO_OWNER | TODO_OWNER | |
| playback_start_ms | TODO_OWNER | TODO_OWNER | |
| **end to end** | TODO_OWNER | TODO_OWNER | |

## Cost per call

Agencies care about this more than they care about the architecture. The components:

| Component | Unit | Rate | Per 3 minute call |
|---|---|---|---|
| Twilio inbound voice | per minute | TODO_OWNER | TODO_OWNER |
| Twilio SMS, cold leads only | per message | TODO_OWNER | TODO_OWNER |
| Deepgram streaming | per minute | TODO_OWNER | TODO_OWNER |
| Cartesia | per character | TODO_OWNER | TODO_OWNER |
| LLM, turn generation | per token | TODO_OWNER | TODO_OWNER |
| LLM, end of call extraction | per token | TODO_OWNER | TODO_OWNER |
| **Total** | | | **TODO_OWNER** |

Fill this in from the vendors' current published pricing and from a real call's token and
character counts, not from memory. The turn model and the extraction model are configured
separately (`LLM_MODEL`, `LLM_MODEL_EXTRACTION`) precisely so this table can show the split.

## The model split

Turn generation runs on the fast model because it sits inside the 800 ms budget. The end of
call extraction pass runs on the strong model because it does not: nobody is listening to
silence while it runs. If the budget cannot be met, the lever is the turn model, and the
measured effect of pulling it belongs in this document.

## What raises latency

- A long agent utterance does not raise time to first audio, but it raises the time before
  the caller can speak again without interrupting. Watch `handle_time_turns` in the eval
  summary when changing prompts; a chattier agent shows up there first.
- `DEEPGRAM_ENDPOINTING_MS` trades responsiveness against cutting people off. Tune it with
  the hesitant and noisy personas, and record what the tradeoff cost.
- A cold Cartesia socket adds a TLS handshake. One socket is held open per call for exactly
  this reason.
