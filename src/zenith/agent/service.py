"""Construction of the answering agent over an LM Studio model."""

from __future__ import annotations

from typing import Any

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

Cite every fact you report. A citation is the note title, the heading, and the
line range, all of which every tool result carries.

Respect what the notes actually establish:

- Report a date only when the entry carries one. An entry whose `date_kind` is
  empty is undated. Do not place it on any day.
- `date_kind` of `entry_date` means the date is written on the entry itself.
  `note_date` means the date belongs to the note the entry sits in.
- Only a result carrying `exact_match_verified` proves the exact wording. A
  result found by meaning is related, not quoted. Do not present one as the
  other.
- When you expand context, keep the `evidence` labels. Say whether something is
  direct evidence, something a link led to, or nearby history.

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
    """
    return OpenAIChatModel(
        settings.llm_model,
        provider=OpenAIProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
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
        # Temperature zero: the same question over unchanged notes should not
        # produce a different answer each time.
        model_settings=ModelSettings(temperature=0.0),
        retries=2,
    )
