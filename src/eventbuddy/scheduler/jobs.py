from eventbuddy.common.logging import get_logger

log = get_logger("scheduler.jobs")


def _default_reminder_sender(event_id: str, kind: str) -> int:
    """Real out-of-band reminder send (no TurnContext): Outlook mail to the event's members
    via Graph, plus a durable `scheduled_jobs` status update. Returns the number sent.

    Scheduled reminders are pre-authorized by the schedule the organizer set up, so there is
    no HITL card here (unlike the on-demand `prepare_reminders` flow). Everything degrades:
    no Graph creds → the job marks itself `failed` and sends nothing, never crashing."""
    from eventbuddy.agent.wiring import _graph_creds
    from eventbuddy.capabilities.reminders import ReminderService
    from eventbuddy.data.db import session_scope
    from eventbuddy.data.repositories.audit import AuditRepository
    from eventbuddy.data.repositories.events import EventRepository
    from eventbuddy.data.repositories.members import MemberRepository
    from eventbuddy.data.repositories.scheduled_jobs import ScheduledJobRepository

    with session_scope() as s:
        ev = EventRepository(s).get(event_id)
        if ev is None:
            return 0
        event_name = ev.event_name
        recipients = [m.email for m in MemberRepository(s).list(event_id) if m.email]

    if not _graph_creds():
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(event_id=event_id, job_type=kind, status="failed")
        log.warning(f"reminder {kind} for {event_id}: Graph not configured — skipped")
        return 0

    from eventbuddy.integrations.graph.client import GraphClient
    from eventbuddy.integrations.graph.token import MsalTokenProvider

    svc = ReminderService(GraphClient(MsalTokenProvider()))
    for email in recipients:  # individually — never a shared To/CC (PII rule §11)
        svc.remind_outlook(email=email, task_name="your event tasks", event_name=event_name)

    with session_scope() as s:
        ScheduledJobRepository(s).set_status(event_id=event_id, job_type=kind, status="sent")
        AuditRepository(s).record(
            event_id=event_id, actor_user_id="scheduler", action="reminder",
            tool_name=kind, payload={"kind": kind, "recipients": len(recipients)}, result="sent",
        )
    return len(recipients)


def run_reminder(event_id: str, kind: str, sender=None) -> None:
    """APScheduler entry point for D-3/D-1/H-1 reminders. `sender` is injectable for tests;
    production uses the real Graph-backed sender. Best-effort: a failure must never crash the
    scheduler (mirrors `run_summarize_sessions`)."""
    sender = sender or _default_reminder_sender
    try:
        n = sender(event_id, kind)
        log.info(f"reminder fired event={event_id} kind={kind} sent={n}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"reminder {kind} for {event_id} failed: {type(e).__name__}: {e}")


def run_feedback_send(event_id: str) -> None:
    # Implementation 2 (feedback/report plane) wires the real Forms dispatch.
    log.info(f"feedback_send fired event={event_id}")


def run_feedback_followup(event_id: str) -> None:
    # Implementation 2 (feedback/report plane) wires the real follow-up nudge.
    log.info(f"feedback_followup fired event={event_id}")


def run_summarize_sessions(summarizer) -> None:
    """Periodic rolling-summary consolidation (Phase 1.7). Best-effort: a failure (e.g. no
    DB/LLM creds) must not crash the scheduler."""
    try:
        updated = summarizer.summarize_all()
        if updated:
            log.info(f"summarize_sessions updated {updated} thread(s)")
    except Exception as e:  # noqa: BLE001
        log.warning(f"summarize_sessions skipped: {type(e).__name__}: {e}")
