# AGENTS.md - ArcAgent

Inbound voice agent for dental implant lead qualification.
Pipeline: Twilio Media Streams (mulaw 8kHz) -> Deepgram streaming STT -> LangGraph agent -> Cartesia streaming TTS -> Twilio.
Hot leads warm-transfer to a coordinator; cold leads get a callback slot and an SMS.
Evaluated with a fixed 30-persona harness. Copy this file to CLAUDE.md for Claude Code.

## Layout
- arcagent/app.py            FastAPI: /voice/inbound (TwiML), /voice/stream (WebSocket)
- arcagent/telephony/        Twilio frame parsing, mark/clear, transfer, SMS
- arcagent/speech/           deepgram_stt.py, cartesia_tts.py
- arcagent/agent/            graph.py, state.py, nodes/, prompts/v<N>/, scoring.py
- arcagent/persistence/      SQLAlchemy models, repo
- evals/                     personas/*.yaml, simulator.py, run_text.py, run_audio.py, metrics.py, compare_runs.py
- dashboard/app.py           Streamlit
- tests/                     pytest
- docs/                      architecture, compliance_design, failure_modes, vendor_params, scoring

## Commands
- Setup:   docker compose up -d && alembic upgrade head
- Run:     uvicorn arcagent.app:app --reload   (owner runs ngrok separately)
- Test:    pytest -q
- Lint:    ruff check . && ruff format --check .
- Eval:    python -m evals.run_text --run-name <name> --repeats 3
- Compare: python -m evals.compare_runs <old_run_id> <new_run_id>

## Rules
1. Secrets come from env via config.py. Never hardcode keys, numbers, or URLs.
2. Never write numbers into README.md or docs/. Results tables are rendered by scripts/render_eval_results.py from the DB.
3. Do not edit owner-authored files: arcagent/agent/prompts/**, evals/personas/**, docs/scoring.md, docs/conversation_design.md, docs/vendor_params.md. Add a new prompts/v<N>/ directory instead of editing an old one.
4. Vendor parameters for Twilio Media Streams, Deepgram, and Cartesia are listed in docs/vendor_params.md. If a parameter is not there, ask; do not guess.
5. Audio stays mulaw 8kHz end to end. No resampling in application code.
6. Scoring and routing live in scoring.py, are pure functions, and are unit-tested. The LLM never decides hot vs cold.
7. Outbound audio has one writer task. Barge-in cancellation is tested (tests/test_barge_in.py), not assumed.
8. Every turn logs stt_final_ms, llm_ttft_ms, tts_first_byte_ms, playback_start_ms. Changes to the audio path keep these populated.
9. Logs redact phone numbers, emails, names. Transcript text is never logged at INFO.
10. No em-dashes in prose or docs.

## Definition of done
- Plan proposed and confirmed before code
- Tests added for new behavior; full suite run; output pasted in the summary
- No edits outside the task scope
- Summary lists new dependencies and why

## Skills
- Load twilio-webhook-architecture and twilio-voice-ai-agent-advisor for telephony tasks; twilio-sms-send-message for the callback SMS; twilio-security-hardening for webhook signature validation.
- Load deepgram-api for STT parameters; cartesia-api for TTS output formats.
- Load langgraph (langchain-ai/langchain-skills) for graph, state, and checkpointer work.
- Use test-driven-development for scoring, graph transitions, and barge-in. Use systematic-debugging when the owner pastes call notes or logs.
- Use verification-before-completion before every summary.
