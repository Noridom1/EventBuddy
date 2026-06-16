from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import Task


class TaskRepository:
    def __init__(self, session: Session):
        self.s = session

    def create(self, event_id: str, task_name: str, **kwargs) -> Task:
        t = Task(event_id=event_id, task_name=task_name, **kwargs)
        self.s.add(t)
        return t

    def list(self, event_id: str) -> list[Task]:
        return list(self.s.scalars(select(Task).where(Task.event_id == event_id)))

    def by_assignee(self, assignee_id: str) -> list[Task]:
        return list(self.s.scalars(select(Task).where(Task.assignee_id == assignee_id)))

    def by_assignee_in_event(self, assignee_id: str, event_id: str) -> list[Task]:
        """The caller's tasks within a single event — backs `list_my_tasks` once an event is
        focused, so the list changes as the user switches focus (not a global cross-event dump)."""
        return list(self.s.scalars(
            select(Task).where(Task.assignee_id == assignee_id, Task.event_id == event_id)
        ))

    def due_within(self, event_id: str, hours: int) -> list[Task]:
        cutoff = datetime.now(UTC) + timedelta(hours=hours)
        return [
            t for t in self.list(event_id)
            if t.due_date and t.status != "done" and t.due_date <= cutoff
        ]

    def set_status(self, task_id: str, status: str) -> None:
        self.s.get(Task, task_id).status = status
