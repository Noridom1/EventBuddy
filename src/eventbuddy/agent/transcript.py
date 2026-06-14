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


def _sent_at_of(m: BaseMessage) -> datetime | None:
    """Pull the real send-time a message is carrying in `additional_kwargs` (set by
    `RequestContext.tag`), parsing the ISO string back to a datetime. None if absent."""
    raw = (getattr(m, "additional_kwargs", None) or {}).get("sent_at")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def sent_at_prefix(m: BaseMessage) -> str:
    """A compact `[YYYY-MM-DD HH:MM UTC] ` prefix for a message carrying a send-time, or ""
    when it has none. Rendered only at injection points (rehydrated tail, event snapshot) —
    never stored in `content` — so the model sees *when* without polluting what the
    summarizer reads (Phase 1.9)."""
    sent = _sent_at_of(m)
    if sent is None:
        return ""
    if sent.tzinfo is not None:
        sent = sent.astimezone(UTC)
    return sent.strftime("[%Y-%m-%d %H:%M UTC] ")


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
                created = base + timedelta(microseconds=i)
                # Real send-time: a user turn carries it (ingress); an assistant turn is
                # generated now. Falls back to the ordering time when unknown.
                sent = _sent_at_of(m) if _is_user(m) else None
                s.add(
                    ConversationMessage(
                        thread_id=thread_id,
                        event_id=event_id,
                        role="user" if _is_user(m) else "assistant",
                        speaker_name=getattr(m, "name", None),
                        content=str(m.content),
                        created_at=created,
                        sent_at=sent or created,
                    )
                )
            return len(new)

    def record_turn(
        self,
        thread_id: str,
        *,
        human: BaseMessage,
        assistant_text: str,
        event_id: str | None = None,
    ) -> int:
        """Persist exactly one user turn + one assistant turn — the live per-turn write path
        (Phase 1.9). Unlike `flush_window` it appends only this turn's two rows, so it stays
        correct even when the working window was cold-seeded from a transcript *tail* (where
        a high-water-mark count slice would mis-skip). The user turn's send-time comes from
        `human.additional_kwargs["sent_at"]`; the assistant turn uses generation time."""
        with self._session_factory() as s:
            base = datetime.now(UTC)
            human_sent = _sent_at_of(human) or base
            s.add(
                ConversationMessage(
                    thread_id=thread_id,
                    event_id=event_id,
                    role="user",
                    speaker_name=getattr(human, "name", None),
                    content=str(human.content),
                    created_at=base,
                    sent_at=human_sent,
                )
            )
            assistant_at = base + timedelta(microseconds=1)
            s.add(
                ConversationMessage(
                    thread_id=thread_id,
                    event_id=event_id,
                    role="assistant",
                    speaker_name=None,
                    content=assistant_text,
                    created_at=assistant_at,
                    sent_at=assistant_at,
                )
            )
            return 2

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
        # Carry the real send-time back onto the rebuilt message so the renderer can stamp
        # it at injection points (Phase 1.9). Kept in additional_kwargs, out of `content`.
        extra = {}
        if row.sent_at is not None:
            extra["additional_kwargs"] = {"sent_at": row.sent_at.isoformat()}
        if row.role == "user":
            if row.speaker_name:
                return HumanMessage(content=row.content, name=row.speaker_name, **extra)
            return HumanMessage(content=row.content, **extra)
        return AIMessage(content=row.content, **extra)
