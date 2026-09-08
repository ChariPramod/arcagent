# Prompts, version 1

**Owner authored. The agent scaffolds these files; the wording is yours.**

Every file here is a placeholder marked `TODO_OWNER`. They are deliberately thin: what the
agent says to a frightened 58 year old about the cost of a full arch is a judgement call
that belongs to the person who has heard those calls, and writing both the prompts and the
personas would make the eval meaningless.

Rules that hold whatever you write:

- One file per LLM node, named for the node.
- Never edit a version directory that an eval run has been tagged with. Copy `v1/` to
  `v2/`, edit there, and set `PROMPT_VERSION=v2`.
- The structured output schema is in `arcagent/agent/schemas.py`, not in the prompt. The
  prompt does not need to describe the JSON shape; the API enforces it.
- The constraints in `docs/conversation_design.md` under "What the agent must never do"
  belong in every prompt, not just the ones where they seem likely to come up.
