"""Seed (or clean) demo data for testing the HITL action plane (Implementation 1).

Connects to whatever ``DATABASE_URL`` is configured — the same cloud Postgres the deployed
AgentBase runtime reads (datastores are reachable directly over public TLS), so running
``make seed`` from your laptop populates the *live* DB the deployed agent serves from.

Idempotent: re-running replaces the demo event (its members + tasks cascade-delete first),
so you always get a clean, known state. The ``--host-user-id`` must match the identity you
test as — the Bot Framework Emulator's **User ID** (Settings) or the ``user_id`` you POST to
``/api/dev/handle`` — otherwise "my tasks" / focus won't resolve to you.

Usage:
    venv/bin/python scripts/seed.py [--host-user-id dev-user] [--clean]
"""
import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from eventbuddy.data.db import session_scope
from eventbuddy.domain.models import Event, EventMember, Task

DEMO_EVENT_NAME = "Demo Workshop"


def _remove_existing(session) -> bool:
    ev = session.scalar(select(Event).where(Event.event_name == DEMO_EVENT_NAME))
    if ev is not None:
        session.delete(ev)  # cascade removes its members + tasks
        return True
    return False


def seed(host_user_id: str, clean_only: bool = False) -> None:
    with session_scope() as s:
        removed = _remove_existing(s)
        if clean_only:
            print(f"{'Removed' if removed else 'No'} demo event '{DEMO_EVENT_NAME}'.")
            return

        now = datetime.now(UTC)
        ev = Event(
            event_name=DEMO_EVENT_NAME,
            status="planning",
            objective="Hands-on AI workshop for the team",
            host_user_id=host_user_id,
            start_at=now + timedelta(days=3, hours=2),
            end_at=now + timedelta(days=3, hours=5),
        )
        s.add(ev)
        s.flush()  # assign ev.event_id

        s.add_all([
            EventMember(event_id=ev.event_id, teams_user_id=host_user_id,
                        email="lead@example.com", display_name="Demo Lead", role="host"),
            EventMember(event_id=ev.event_id, email="huy@example.com",
                        display_name="Huy", role="member"),
            EventMember(event_id=ev.event_id, email="mai@example.com",
                        display_name="Mai", role="member"),
        ])
        s.add_all([
            Task(event_id=ev.event_id, task_name="Prepare slides", assignee_id=host_user_id,
                 assignee_email="lead@example.com", due_date=now + timedelta(days=2),
                 status="todo"),
            Task(event_id=ev.event_id, task_name="Book the room", assignee_id=host_user_id,
                 status="in_progress"),
            Task(event_id=ev.event_id, task_name="Send invitations",
                 assignee_email="huy@example.com", status="todo"),
        ])
        print(f"Seeded '{DEMO_EVENT_NAME}' (id {ev.event_id}) — host={host_user_id}, "
              f"3 members, 3 tasks. Focus it with: \"focus on {DEMO_EVENT_NAME}\".")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed/clean EventBuddy demo data.")
    p.add_argument("--host-user-id", default="dev-user",
                   help="teams_user_id of the host (match your Emulator User ID / dev user_id)")
    p.add_argument("--clean", action="store_true", help="remove the demo event and exit")
    args = p.parse_args()
    seed(args.host_user_id, clean_only=args.clean)
