# Vendor parameters

Single source of truth for parameter names used against Twilio Media Streams, Deepgram
streaming, and Cartesia streaming. Code uses only what is listed here. Anything not listed
is stubbed behind an interface with a `TODO_OWNER`, never invented.

**Verification status.** Rows marked `owner-confirmed` are taken from the scope document,
which the owner wrote after reading the vendor docs. Rows marked `TODO_OWNER` are drafted
from the agent's knowledge and must be checked against the live vendor documentation before
any real call is made. When a vendor skill or the live docs disagree with this file, the
live docs win and this file is updated by the owner.

---

## 1. Twilio Media Streams

Connection: Twilio opens a WebSocket to our server after `<Connect><Stream url="wss://..."/>`.
Audio in both directions is base64 encoded mulaw, 8000 Hz, mono, 20 ms per frame
(160 bytes of mulaw per frame). `owner-confirmed`

### Inbound events (Twilio to us)

| Event | Shape | Status |
|---|---|---|
| `connected` | `{"event":"connected","protocol":"Call","version":"1.0.0"}` | TODO_OWNER |
| `start` | `{"event":"start","sequenceNumber":"1","start":{"streamSid":...,"accountSid":...,"callSid":...,"tracks":["inbound"],"mediaFormat":{"encoding":"audio/x-mulaw","sampleRate":8000,"channels":1},"customParameters":{}},"streamSid":...}` | TODO_OWNER |
| `media` | `{"event":"media","sequenceNumber":"2","media":{"track":"inbound","chunk":"1","timestamp":"5","payload":"<base64 mulaw>"},"streamSid":...}` | TODO_OWNER |
| `dtmf` | `{"event":"dtmf","dtmf":{"track":"inbound_track","digit":"1"},"streamSid":...}` | TODO_OWNER |
| `mark` | `{"event":"mark","mark":{"name":"<our name>"},"streamSid":...}` acknowledges playback finished | TODO_OWNER |
| `stop` | `{"event":"stop","stop":{"accountSid":...,"callSid":...},"streamSid":...}` | TODO_OWNER |

### Outbound messages (us to Twilio)

| Message | Shape | Status |
|---|---|---|
| media | `{"event":"media","streamSid":"<sid>","media":{"payload":"<base64 mulaw>"}}` | TODO_OWNER |
| mark | `{"event":"mark","streamSid":"<sid>","mark":{"name":"<name>"}}` | TODO_OWNER |
| clear | `{"event":"clear","streamSid":"<sid>"}` discards buffered audio, used for barge in | TODO_OWNER |

### TwiML and REST

| Use | Value | Status |
|---|---|---|
| Inbound answer | `<Response><Connect><Stream url="wss://{PUBLIC_URL}/voice/stream"/></Connect></Response>` | owner-confirmed |
| Warm transfer | REST update of the live call with `<Response><Dial>{COORDINATOR_NUMBER}</Dial></Response>` | owner-confirmed |
| Webhook signature | `X-Twilio-Signature` header, validated with the auth token over the full URL and the POST body | TODO_OWNER |

---

## 2. Deepgram streaming STT

Endpoint: `wss://api.deepgram.com/v1/listen`. Auth: `Authorization: Token <DEEPGRAM_API_KEY>`. `TODO_OWNER`

| Query parameter | Value we send | Status |
|---|---|---|
| `encoding` | `mulaw` | owner-confirmed |
| `sample_rate` | `8000` | owner-confirmed |
| `channels` | `1` | TODO_OWNER |
| `model` | `nova-2-phonecall` or the current telephony model | TODO_OWNER |
| `interim_results` | `true` | owner-confirmed |
| `endpointing` | `DEEPGRAM_ENDPOINTING_MS`, default 400 | owner-confirmed |
| `utterance_end_ms` | `DEEPGRAM_UTTERANCE_END_MS`, default 1000 | owner-confirmed |
| `smart_format` | `true` | owner-confirmed |
| `vad_events` | `true` | TODO_OWNER |
| `language` / `detect_language` | used for the Spanish fallback path | TODO_OWNER |

| Response message | Fields we read | Status |
|---|---|---|
| `Results` | `channel.alternatives[0].transcript`, `is_final`, `speech_final`, `start`, `duration` | TODO_OWNER |
| `UtteranceEnd` | `last_word_end` | TODO_OWNER |
| `SpeechStarted` | `timestamp` | TODO_OWNER |
| `Metadata` | `request_id` | TODO_OWNER |

| Control message | Shape | Status |
|---|---|---|
| Keepalive | `{"type":"KeepAlive"}` | TODO_OWNER |
| Close | `{"type":"CloseStream"}` | TODO_OWNER |

Audio frames are sent as raw binary WebSocket messages, not base64. `TODO_OWNER`

---

## 3. Cartesia streaming TTS

Endpoint: `wss://api.cartesia.ai/tts/websocket`. Auth and version headers or query
parameters. `TODO_OWNER`

| Field | Value we send | Status |
|---|---|---|
| `model_id` | `CARTESIA_MODEL_ID`, default `sonic-2` | TODO_OWNER |
| `transcript` | the utterance text | TODO_OWNER |
| `voice` | `{"mode":"id","id":"<CARTESIA_VOICE_ID>"}` | TODO_OWNER |
| `output_format` | `{"container":"raw","encoding":"pcm_mulaw","sample_rate":8000}` | owner-confirmed |
| `language` | `en` | TODO_OWNER |
| `context_id` | our per utterance id, used to cancel on barge in | TODO_OWNER |

| Response | Fields we read | Status |
|---|---|---|
| audio chunk | `{"type":"chunk","context_id":...,"data":"<base64 mulaw>","done":false}` | TODO_OWNER |
| done | `{"type":"done","context_id":...,"done":true}` | TODO_OWNER |
| error | `{"type":"error","error":"..."}` | TODO_OWNER |

Cartesia returns raw mulaw with no WAV header when `container` is `raw`, so chunks are
re-framed to 160 byte Twilio frames without any resampling. `owner-confirmed`

---

## 4. Rules

1. No parameter goes into code unless it has a row above.
2. A parameter the agent is unsure about is stubbed behind the vendor client interface with
   a `TODO_OWNER` comment and surfaced in the session summary.
3. Audio stays mulaw 8 kHz from Twilio to Deepgram and from Cartesia back to Twilio. There
   is no resampling anywhere in application code.
