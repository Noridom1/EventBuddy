"""Durable transcript layer (Phase 1.7, memory layer 2).

Overflow + rehydration over Postgres `conversation_messages`. Persists **user/assistant
turns only** — tool-call `AIMessage`s and `ToolMessage`s are dropped (they live only in the
Redis working window). `rehydrate` seeds an empty working window from the most-recent turns
that fit the token budget."""
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import func, select

from eventbuddy.data.db import session_scope
from eventbuddy.domain.models import ConversationMessage


def _is_user(m: BaseMessage) -> bool:
    return isinstance(m, HumanMessage)


def _is_assistant(m: BaseMessage) -> bool:
    # A final assistant turn: an AIMessage with text and no pending tool calls.
    return isinstance(m, AIMessage) and not m.tool_calls and bool(str(m.content).strip())


def _durable(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [m for m in messages if _is_user(m) or _is_assistant(m)]


class Transcript:
    def __init__(
        self,
        *,
        session_factory: Callable = session_scope,
        token_counter: Callable[[str], int] | None = None,
    ):
        self._session_factory = session_factory
        self._count = token_counter or (lambda text: len(text.split()))

    def flush_window(
        self, thread_id: str, messages: list[BaseMessage], *, event_id: str | None = None
    ) -> int:
        """Persist user/assistant turns not yet stored. Idempotent via a per-thread
        high-water mark (the count of already-persisted turns), so re-flushing the same
        (or a grown) window never double-writes. Returns the number of new rows."""
        durable = _durable(messages)
        with self._session_factory() as s:
            already = s.scalar(
                select(func.count())
                .select_from(ConversationMessage)
                .where(ConversationMessage.thread_id == thread_id)
            )
            new = durable[already:]
            # Postgres now() is the transaction timestamp — every row in one flush would
            # share it and lose ordering. Stamp explicit, strictly-increasing times so
            # rehydrate can order turns chronologically.
            base = datetime.now(UTC)
            for i, m in enumerate(new):
                s.add(
                    ConversationMessage(
                        thread_id=thread_id,
                        event_id=event_id,
                        role="user" if _is_user(m) else "assistant",
                        speaker_name=getattr(m, "name", None),
                        content=str(m.content),
                        created_at=base + timedelta(microseconds=i),
                    )
                )
            return len(new)

    def rehydrate(self, thread_id: str, budget: int = 4096) -> list[BaseMessage]:
        """Return the most-recent turns whose running token total <= budget, oldest-first.
        Empty list for an unknown thread."""
        with self._session_factory() as s:
            rows = list(
                s.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.thread_id == thread_id)
                    .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
                )
            )
            kept, total = [], 0
            for r in rows:
                t = self._count(r.content)
                if kept and total + t > budget:
                    break
                kept.append(r)
                total += t
            kept.reverse()
            return [self._to_message(r) for r in kept]

    @staticmethod
    def _to_message(row: ConversationMessage) -> BaseMessage:
        if row.role == "user":
            if row.speaker_name:
                return HumanMessage(content=row.content, name=row.speaker_name)
            return HumanMessage(content=row.content)
        return AIMessage(content=row.content)
