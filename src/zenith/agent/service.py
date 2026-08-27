"""Construction of the answering agent over an LM Studio model."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from zenith.agent.tools import TOOLS
from zenith.core.config import Settings
from zenith.library import Zenith


INSTRUCTIONS = """
You answer questions about one person's Markdown notes. The notes are the only
source you have; you have no other knowledge of this person's life or work.

Search before you answer. Never answer from memory, and never invent a note, a
date, or a quotation.

# How to cite

End every fact you report with a citation, in exactly this form:

    [Note Title, Heading, lines N-M]

Copy all three parts from the tool result that gave you the fact: its `note`,
its `heading`, and its `lines`. A correct sentence looks like this:

    You added an llm based parsing model. [News Resolution, 2026-08-17, lines 6-9]

When the result has no heading, write `[Note Title, lines N-M]` instead.

Cite even when the question does not ask you to. A sentence that reports a fact
without a citation is not finished.

Never print an `entry_id` or a `source_entry_id`. Those are internal identifiers
you pass to `expand_context`. They are not citations, and they mean nothing to
the person reading your answer. This is wrong:

    You cleaned up the pipeline. [fb3cf265-36fe-5a66-b619-29485c83dc0e]

So is a bare note title with no lines, like `[News Resolution]`. Give the note,
the heading, and the lines every time.

# What the notes establish

- Report a date only when the entry carries one. An entry whose `date_kind` is
  empty is undated. Do not place it on any day.
- `date_kind` of `entry_date` means the date is written on the entry itself.
  `note_date` means the date belongs to the note the entry sits in.
- Only a result carrying `exact_match_verified` proves the exact wording. A
  result found by meaning is related, not quoted. Do not present one as the
  other.
- When you expand context, keep the `evidence` labels. Say whether something is
  direct evidence, something a link led to, or nearby history.
- A result carrying `text_truncated` or `content_truncated` is a fragment, not
  the whole thing. Never conclude that a note does not mention something from a
  fragment of it. Read the note, or search again with narrower words.
- If a tool returns a different note than the one you asked for, say so, and do
  not answer as though it were the note the question was about.

Say plainly when the notes do not answer the question. That is a useful answer.
Guessing is not.
""".strip()

# A local model has a finite patience for tool loops. These caps end a confused
# run instead of letting it spin.
DEFAULT_LIMITS = UsageLimits(request_limit=12, tool_calls_limit=20)


def build_model(settings: Settings) -> OpenAIChatModel:
    """Build the LM Studio model described by the settings.

    LM Studio is OpenAI-compatible rather than OpenAI. Strict tool definitions
    and `tool_choice='required'` are both off, because a compatible server is
    not obliged to support either.

    The client is built here rather than left to the provider so the request
    timeout and the retry count are ours. Both defaults belong to a hosted API
    and are wrong for a local model on the far side of a desktop application.
    """
    return OpenAIChatModel(
        settings.llm_model,
        provider=OpenAIProvider(
            openai_client=AsyncOpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout,
                # The client retries a timeout twice by default, so a stalled
                # model would cost three times the timeout before reporting it.
                max_retries=0,
            )
        ),
        profile=OpenAIModelProfile(
            openai_supports_strict_tool_definition=False,
            openai_supports_tool_choice_required=False,
        ),
    )


def build_agent(settings: Settings, *, model: Any | None = None) -> Agent[Zenith, str]:
    """Build the answering agent. Pass `model` to run against a test model."""
    return Agent(
        model or build_model(settings),
        deps_type=Zenith,
        tools=TOOLS,
        instructions=INSTRUCTIONS,
        # Sent on every request, so it decides the sampling rather than any
        # preset the LM Studio server happens to hold. Zero by default, to keep
        # the answer as close to reproducible as the server allows. It is not a
        # guarantee: a mixture-of-experts model served by LM Studio still varies
        # between runs on a byte-identical prompt, measured at roughly one run
        # in three. Treat a repeated answer as likely, never as promised.
        model_settings=ModelSettings(temperature=settings.llm_temperature),
        retries=2,
    )
