"""Talk to the agent in text, with no audio and no telephony.

    python -m scripts.repl                 # real model, needs LLM_API_KEY
    python -m scripts.repl --prompts v2    # try a prompt version
    python -m scripts.repl --threshold 70

Read the conversation before you touch audio. If it reads badly here it will sound worse
on the phone.
"""

from __future__ import annotations

import argparse
import asyncio

from arcagent.agent.graph import AgentConfig, Conversation
from arcagent.agent.llm import AnthropicStructuredLLM
from arcagent.config import get_settings
from arcagent.logging import configure_logging


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Text REPL for the qualification agent.")
    parser.add_argument("--prompts", default=settings.prompt_version, help="prompt version")
    parser.add_argument("--threshold", type=int, default=settings.handoff_threshold)
    parser.add_argument(
        "--no-coordinator",
        action="store_true",
        help="simulate nobody being available to take a warm transfer",
    )
    parser.add_argument("--model", default=None, help="override the turn model id")
    parser.add_argument("--quiet", action="store_true", help="hide the state summary")
    return parser.parse_args()


def show_state(conversation: Conversation) -> None:
    fields = conversation.fields
    populated = {
        key: value
        for key, value in fields.as_lead_row().items()
        if value not in (None, "", [], False)
    }
    print(f"\n  node: {conversation.state['current_node']}")
    print(f"  fields: {populated}")
    if conversation.state.get("score") is not None:
        print(f"  score: {conversation.state['score']} -> {conversation.state['decision']}")
        print(f"  breakdown: {conversation.state['score_breakdown']}")
    print()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(level="WARNING")

    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY is not set. Put it in .env.")

    conversation = Conversation(
        AgentConfig(
            llm=AnthropicStructuredLLM(settings),
            prompt_version=args.prompts,
            threshold=args.threshold,
            coordinator_available=not args.no_coordinator,
            model=args.model,
        )
    )

    for line in await conversation.start():
        print(f"agent: {line}")

    while not conversation.finished:
        try:
            caller = (await asyncio.to_thread(input, "you:   ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if caller in {"/quit", "/exit"}:
            break
        if caller == "/state":
            show_state(conversation)
            continue
        if not caller:
            continue
        for line in await conversation.say(caller):
            print(f"agent: {line}")
        if not args.quiet:
            show_state(conversation)

    print(f"\noutcome: {conversation.outcome}")
    if conversation.state.get("score") is not None:
        print(f"score:   {conversation.state['score']} -> {conversation.state['decision']}")


if __name__ == "__main__":
    asyncio.run(main())
