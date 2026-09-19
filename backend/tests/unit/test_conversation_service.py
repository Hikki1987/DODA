"""Unit test for `doda.application.conversation_service._messages_to_history`
— the character-budget truncation that picks which stored messages become
model context (no DB needed: it's a pure function over in-memory `Message`
objects, same reasoning `tests/unit/test_tool_policy.py` already applies to
`doda.domain.action.tool_policy`).
"""

import uuid

from doda.application.conversation_service import _messages_to_history
from doda.domain.conversation.models import Message, MessageRole


def _message(content: str) -> Message:
    return Message(
        customer_id=uuid.uuid4(), conversation_id=uuid.uuid4(), role=MessageRole.USER, content=content
    )


def test_messages_to_history_keeps_the_most_recent_messages_and_drops_older_ones_over_budget() -> None:
    # Oldest first, as stored/returned by list_messages — _messages_to_history
    # itself walks them newest-first (`reversed(messages)`) to decide what to
    # KEEP, then restores chronological order for the returned history.
    messages = [_message("a" * 10), _message("b" * 10), _message("c" * 10)]

    history = _messages_to_history(messages, max_chars=15)

    # Budget only fits the newest message alone (10 chars) plus a bit more,
    # not two full 10-char messages (20 > 15) — so the oldest two are
    # dropped, not the newest.
    assert [turn.content for turn in history] == ["c" * 10]


def test_messages_to_history_keeps_everything_when_well_under_budget() -> None:
    messages = [_message("a" * 5), _message("b" * 5), _message("c" * 5)]

    history = _messages_to_history(messages, max_chars=1000)

    assert [turn.content for turn in history] == ["a" * 5, "b" * 5, "c" * 5]
