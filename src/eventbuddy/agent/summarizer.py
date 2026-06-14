"""Rolling summary layer (Phase 1.7, memory layer 3).

A compact running summary per session of everything older than the rehydration tail, so a
long event keeps its early context inside the 4096-token budget. Refreshed out of band by a
background job (no per-turn latency) using `LLMGateway.summarize` — a non-chat LLM use, not
the ReAct loop. The runner reads `get_summary` to prepend context when seeding an empty
working window."""
from collections.abc import Callable

from sqlalchemy import select

from eventbuddy.data.db import session_scope
from eventbuddy.domain.models import ConversationMessage, SessionSummary

SUMMARY_INSTRUCTION = (
    "You maintain a running summary of an ongoing event conversation. Given the previous "
    "summary and the new turns, produce an updated, concise summary that preserves names, "
    "decisions, commitments, dates, and open questions. Keep it under 200 words."
)


class Summarizer:
    def __init__(self, llm, *, session_factory: Callable = session_scope):
        self._llm = llm
        self._sf = session_factory

    def get_summary(self, thread_id: str) -> str:
        with self._sf() as s:
            row = s.get(SessionSummary, thread_id)
            return row.summary if row else ""

    def summarize_session(self, thread_id: str) -> bool:
        """Fold transcript turns newer than `covered_through` into the rolling summary and
        advance the watermark. No new turns → no-op (no LLM call). Returns True if updated."""
        with self._sf() as s:
            row = s.get(SessionSummary, thread_id)
            covered = row.covered_through if row else None
            q = select(ConversationMessage).where(ConversationMessage.thread_id == thread_id)
            if covered is not None:
                q = q.where(ConversationMessage.created_at > covered)
            new_msgs = list(s.scalars(q.order_by(ConversationMessage.created_at)))
            if not new_msgs:
                return False

            prior = row.summary if row else ""
            new_turns = "\n".join(f"{m.role}: {m.content}" for m in new_msgs)
            folded = self._llm.summarize(
                f"Previous summary:\n{prior}\n\nNew turns:\n{new_turns}",
                instruction=SUMMARY_INSTRUCTION,
            )
            watermark = new_msgs[-1].created_at
            if row is None:
                s.add(
                    SessionSummary(
                        thread_id=thread_id, summary=folded, covered_through=watermark
                    )
                )
            else:
                row.summary = folded
                row.covered_through = watermark
            return True

    def _threads_needing_summary(self, s) -> list[str]:
        """Distinct threads with at least one transcript turn newer than their watermark."""
        thread_ids = list(s.scalars(select(ConversationMessage.thread_id).distinct()))
        pending = []
        for tid in thread_ids:
            summ = s.get(SessionSummary, tid)
            covered = summ.covered_through if summ else None
            q = select(ConversationMessage.id).where(ConversationMessage.thread_id == tid)
            if covered is not None:
                q = q.where(ConversationMessage.created_at > covered)
            if s.scalar(q.limit(1)):
                pending.append(tid)
        return pending

    def summarize_all(self) -> int:
        """Summarize every thread with new turns. Returns the number updated. Used by the
        periodic APScheduler job."""
        with self._sf() as s:
            threads = self._threads_needing_summary(s)
        updated = 0
        for thread_id in threads:
            if self.summarize_session(thread_id):
                updated += 1
        return updated
