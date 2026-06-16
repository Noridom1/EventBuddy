"""Seed (or clean) demo data for testing & demoing EventBuddy.

Connects to whatever ``DATABASE_URL`` is configured — the same cloud Postgres the deployed
AgentBase runtime reads (datastores are reachable directly over public TLS), so running
``make seed`` from your laptop populates the *live* DB the deployed agent serves from.

It seeds **several events** with varied statuses, rosters, and tasks so a demo can show:
  • event management — multiple events the host owns, in different lifecycle stages
  • switching focus between events ("list my events", "focus on the AI Summit")
  • task management — tasks per event with assignees + due dates (overdue / due-soon / future)
  • updating task status — a healthy spread of todo / in_progress / done to move around
  • report generation — a completed event with analyzed feedback to aggregate

Idempotent: re-running first deletes every demo event by name (members + tasks + feedback
cascade-delete), so you always land on a clean, known state. The ``--host-user-id`` must match
the identity you test as — the Bot Framework Emulator's **User ID** (Settings) or the
``user_id`` you POST to ``/api/dev/handle`` — otherwise "my tasks" / focus won't resolve to you.
The host is enrolled as a roster member of every event so ``list my events`` returns them all.

Usage:
    venv/bin/python scripts/seed.py [--host-user-id dev-user] [--clean]
"""
import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from eventbuddy.data.db import session_scope
from eventbuddy.domain.models import Event, EventMember, FeedbackResponse, Task

# Every event this script owns. Listed here so --clean (and the pre-seed wipe) removes them all.
DEMO_EVENT_NAMES = [
    "AI Innovation Summit 2026",
    "Engineering Team Offsite",
    "Spring Product Hackathon",
    "New Hire Onboarding (May Cohort)",
]


def _remove_existing(session) -> int:
    evs = session.scalars(
        select(Event).where(Event.event_name.in_(DEMO_EVENT_NAMES))
    ).all()
    for ev in evs:
        session.delete(ev)  # cascade removes members + tasks + feedback
    return len(evs)


def _member(ev_id, *, name, email, role="member", user_id=None, status="registered"):
    return EventMember(
        event_id=ev_id, teams_user_id=user_id, email=email, display_name=name,
        role=role, registration_status=status,
    )


def seed(host_user_id: str, clean_only: bool = False) -> None:
    with session_scope() as s:
        removed = _remove_existing(s)
        if clean_only:
            print(f"Removed {removed} demo event(s).")
            return

        now = datetime.now(UTC)
        # Time anchors used across the seed (relative to "now" so the demo always reads right).
        def days(n, hours=0):
            return now + timedelta(days=n, hours=hours)

        # ── Event 1: the flagship — ACTIVE, rich roster + tasks across every status ──────────
        summit = Event(
            event_name="AI Innovation Summit 2026", status="active",
            objective="Full-day external summit showcasing our AI platform to 200 attendees",
            host_user_id=host_user_id, location="Grand Conference Hall, Floor 12",
            start_at=days(5, 1), end_at=days(5, 9),
            registration_link="https://aka.ms/ai-summit-2026",
            feedback_form_url="https://forms.office.com/r/ai-summit-feedback",
        )
        # ── Event 2: PLANNING — internal offsite, fewer tasks, mid-stage ─────────────────────
        offsite = Event(
            event_name="Engineering Team Offsite", status="planning",
            objective="Two-day team offsite: strategy, workshops, and team building",
            host_user_id=host_user_id, location="Lakeview Resort, Da Lat",
            start_at=days(26), end_at=days(27),
        )
        # ── Event 3: IDEATION — earliest stage, just a couple of seed tasks ──────────────────
        hackathon = Event(
            event_name="Spring Product Hackathon", status="ideation",
            objective="48-hour internal hackathon to prototype new product ideas",
            host_user_id=host_user_id,
            start_at=days(52), end_at=days(54),
        )
        # ── Event 4: COMPLETED — finished, all tasks done, has feedback for report demo ──────
        onboarding = Event(
            event_name="New Hire Onboarding (May Cohort)", status="completed",
            objective="Week-long onboarding program for 12 new engineering hires",
            host_user_id=host_user_id, location="Training Room B + Teams",
            start_at=days(-12), end_at=days(-8),
            feedback_form_url="https://forms.office.com/r/onboarding-may-feedback",
        )

        s.add_all([summit, offsite, hackathon, onboarding])
        s.flush()  # assign event_ids

        # ── Rosters. The host is enrolled in every event so `list my events` returns all 4. ──
        s.add_all([
            # AI Innovation Summit
            _member(summit.event_id, name="Demo Lead", email="lead@example.com",
                    role="host", user_id=host_user_id),
            _member(summit.event_id, name="Huy Nguyen", email="huy@example.com",
                    role="moderator"),
            _member(summit.event_id, name="Mai Tran", email="mai@example.com"),
            _member(summit.event_id, name="Linh Pham", email="linh@example.com"),
            _member(summit.event_id, name="David Chen", email="david@example.com",
                    status="pending"),

            # Engineering Team Offsite
            _member(offsite.event_id, name="Demo Lead", email="lead@example.com",
                    role="host", user_id=host_user_id),
            _member(offsite.event_id, name="Huy Nguyen", email="huy@example.com"),
            _member(offsite.event_id, name="Sara Lee", email="sara@example.com",
                    status="pending"),

            # Spring Product Hackathon
            _member(hackathon.event_id, name="Demo Lead", email="lead@example.com",
                    role="host", user_id=host_user_id),
            _member(hackathon.event_id, name="Mai Tran", email="mai@example.com",
                    status="pending"),

            # New Hire Onboarding (completed)
            _member(onboarding.event_id, name="Demo Lead", email="lead@example.com",
                    role="host", user_id=host_user_id),
            _member(onboarding.event_id, name="Linh Pham", email="linh@example.com"),
            _member(onboarding.event_id, name="David Chen", email="david@example.com"),
        ])

        # ── Tasks. Spread across todo / in_progress / done with overdue, due-soon, and future
        #    due dates so "my tasks", reminders, and status updates all have material. ────────
        s.add_all([
            # AI Innovation Summit — the focus of the task-management demo
            Task(event_id=summit.event_id, task_name="Finalize keynote speaker",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(2), status="in_progress"),
            Task(event_id=summit.event_id, task_name="Book main auditorium",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(-3), status="done"),
            Task(event_id=summit.event_id, task_name="Set up registration page",
                 assignee_email="huy@example.com", due_date=days(-1), status="in_progress"),
            Task(event_id=summit.event_id, task_name="Design event banner & signage",
                 assignee_email="mai@example.com", due_date=days(4), status="todo"),
            Task(event_id=summit.event_id, task_name="Order catering for 200",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(3), status="todo"),
            Task(event_id=summit.event_id, task_name="Confirm AV & live-stream setup",
                 assignee_email="linh@example.com", due_date=days(1), status="todo"),
            Task(event_id=summit.event_id, task_name="Send speaker invitations",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(-6), status="done"),

            # Engineering Team Offsite — planning-stage tasks
            Task(event_id=offsite.event_id, task_name="Confirm resort booking",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(7), status="in_progress"),
            Task(event_id=offsite.event_id, task_name="Draft two-day agenda",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(10), status="todo"),
            Task(event_id=offsite.event_id, task_name="Arrange transportation",
                 assignee_email="sara@example.com", due_date=days(14), status="todo"),

            # Spring Product Hackathon — ideation-stage seeds
            Task(event_id=hackathon.event_id, task_name="Define judging criteria",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(20), status="todo"),
            Task(event_id=hackathon.event_id, task_name="Line up mentors",
                 assignee_email="mai@example.com", due_date=days(25), status="todo"),

            # New Hire Onboarding — completed event, everything done
            Task(event_id=onboarding.event_id, task_name="Prepare welcome packets",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(-13), status="done"),
            Task(event_id=onboarding.event_id, task_name="Schedule mentor pairings",
                 assignee_email="linh@example.com", due_date=days(-11), status="done"),
            Task(event_id=onboarding.event_id, task_name="Collect feedback survey",
                 assignee_id=host_user_id, assignee_email="lead@example.com",
                 due_date=days(-7), status="done"),
        ])

        # ── Feedback for the completed event so "focus on onboarding" → "generate report"
        #    has real, analyzed data to aggregate. ─────────────────────────────────────────
        s.add_all([
            FeedbackResponse(
                event_id=onboarding.event_id, respondent_id="linh@example.com",
                raw_payload={"rating": 5, "comment": "Mentor pairing was incredibly helpful",
                             "email": "linh@example.com"},
                sentiment="positive", themes={"tags": ["mentorship", "content"]}),
            FeedbackResponse(
                event_id=onboarding.event_id, respondent_id="david@example.com",
                raw_payload={"rating": 4, "comment": "Great overall, first day felt rushed",
                             "email": "david@example.com"},
                sentiment="positive", themes={"tags": ["pacing"]}),
            FeedbackResponse(
                event_id=onboarding.event_id, respondent_id="anon-1",
                raw_payload={"rating": 2, "comment": "Too much info crammed into day one"},
                sentiment="negative", themes={"tags": ["pacing", "timing"]}),
        ])

        print(
            "Seeded 4 demo events for host="
            f"{host_user_id}:\n"
            "  • AI Innovation Summit 2026 — active, 5 members, 7 tasks (the task-mgmt demo)\n"
            "  • Engineering Team Offsite — planning, 3 members, 3 tasks\n"
            "  • Spring Product Hackathon — ideation, 2 members, 2 tasks\n"
            "  • New Hire Onboarding (May Cohort) — completed, 3 tasks done, 3 feedback rows\n\n"
            "Try this demo flow:\n"
            "  1. \"list my events\"\n"
            "  2. \"focus on the AI Summit\"\n"
            "  3. \"what are my tasks?\"  /  \"show all tasks\"\n"
            "  4. \"mark 'order catering' as in progress\" / \"set registration page to done\"\n"
            "  5. \"focus on the onboarding event\" then \"generate the report\"\n"
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed/clean EventBuddy demo data.")
    p.add_argument("--host-user-id", default="dev-user",
                   help="teams_user_id of the host (match your Emulator User ID / dev user_id)")
    p.add_argument("--clean", action="store_true", help="remove all demo events and exit")
    args = p.parse_args()
    seed(args.host_user_id, clean_only=args.clean)
