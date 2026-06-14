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


def _feedback_form_link(event_id: str) -> str:
    """Resolve the templated feedback Forms link for an event ('' if unconfigured)."""
    from eventbuddy.config import settings
    url = settings.feedback_form_url or ""
    return url.format(event_id=event_id) if "{event_id}" in url else url


def _non_responders(member_emails: list[str], responded: set[str]) -> list[str]:
    """Members who haven't submitted feedback (case-insensitive on email)."""
    return [e for e in member_emails if e.strip().lower() not in responded]


def _send_form_individually(event_name: str, form_link: str, emails: list[str]) -> int:
    """Mail the Forms link to each recipient one-by-one (never a shared To/CC — PII §11)."""
    from eventbuddy.capabilities.feedback import FeedbackDispatchService
    from eventbuddy.integrations.graph.client import GraphClient
    from eventbuddy.integrations.graph.token import MsalTokenProvider

    svc = FeedbackDispatchService(GraphClient(MsalTokenProvider()))
    for email in emails:
        svc.send_form(event_name=event_name, form_link=form_link, member_emails=[email])
    return len(emails)


def _default_feedback_sender(event_id: str) -> int:
    """Dispatch the feedback Forms link to every member (out-of-band, no HITL — the schedule
    pre-authorizes it). Degrades like the reminder sender: no link/creds → mark failed, send
    nothing, never crash."""
    from eventbuddy.agent.wiring import _graph_creds
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
        event_form_url = ev.feedback_form_url  # per-event link (Option 1) wins
        emails = [m.email for m in MemberRepository(s).list(event_id) if m.email]

    form_link = event_form_url or _feedback_form_link(event_id)
    if not form_link or not _graph_creds():
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(
                event_id=event_id, job_type="feedback_send", status="failed")
        log.warning(f"feedback_send for {event_id}: form link / Graph not configured — skipped")
        return 0

    n = _send_form_individually(event_name, form_link, emails)
    with session_scope() as s:
        ScheduledJobRepository(s).set_status(
            event_id=event_id, job_type="feedback_send", status="sent")
        AuditRepository(s).record(
            event_id=event_id, actor_user_id="scheduler", action="feedback_send",
            tool_name="feedback_send", payload={"recipients": n}, result="sent",
        )
    return n


def _default_followup_sender(event_id: str) -> int:
    """Nudge only members who haven't responded yet (architecture §7.5). Non-responders =
    member emails minus the emails already present in `feedback_responses`."""
    from eventbuddy.agent.wiring import _graph_creds
    from eventbuddy.data.db import session_scope
    from eventbuddy.data.repositories.audit import AuditRepository
    from eventbuddy.data.repositories.events import EventRepository
    from eventbuddy.data.repositories.feedback import FeedbackRepository
    from eventbuddy.data.repositories.members import MemberRepository
    from eventbuddy.data.repositories.scheduled_jobs import ScheduledJobRepository

    with session_scope() as s:
        ev = EventRepository(s).get(event_id)
        if ev is None:
            return 0
        event_name = ev.event_name
        event_form_url = ev.feedback_form_url  # per-event link (Option 1) wins
        member_emails = [m.email for m in MemberRepository(s).list(event_id) if m.email]
        responded = FeedbackRepository(s).respondent_emails(event_id)
    non_responders = _non_responders(member_emails, responded)

    form_link = event_form_url or _feedback_form_link(event_id)
    if not form_link or not _graph_creds():
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(
                event_id=event_id, job_type="feedback_followup", status="failed")
        log.warning(f"feedback_followup for {event_id}: not configured — skipped")
        return 0
    if not non_responders:
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(
                event_id=event_id, job_type="feedback_followup", status="sent")
        log.info(f"feedback_followup for {event_id}: everyone responded — nothing to send")
        return 0

    n = _send_form_individually(event_name, form_link, non_responders)
    with session_scope() as s:
        ScheduledJobRepository(s).set_status(
            event_id=event_id, job_type="feedback_followup", status="sent")
        AuditRepository(s).record(
            event_id=event_id, actor_user_id="scheduler", action="feedback_followup",
            tool_name="feedback_followup", payload={"recipients": n}, result="sent",
        )
    return n


def run_feedback_send(event_id: str, sender=None) -> None:
    """APScheduler entry for the post-event feedback dispatch. `sender` is injectable for
    tests; best-effort (a failure must never crash the scheduler)."""
    sender = sender or _default_feedback_sender
    try:
        n = sender(event_id)
        log.info(f"feedback_send fired event={event_id} sent={n}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"feedback_send for {event_id} failed: {type(e).__name__}: {e}")


def run_feedback_followup(event_id: str, sender=None) -> None:
    """APScheduler entry for the +24h non-responder nudge. Injectable + best-effort."""
    sender = sender or _default_followup_sender
    try:
        n = sender(event_id)
        log.info(f"feedback_followup fired event={event_id} sent={n}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"feedback_followup for {event_id} failed: {type(e).__name__}: {e}")


def run_summarize_sessions(summarizer) -> None:
    """Periodic rolling-summary consolidation (Phase 1.7). Best-effort: a failure (e.g. no
    DB/LLM creds) must not crash the scheduler."""
    try:
        updated = summarizer.summarize_all()
        if updated:
            log.info(f"summarize_sessions updated {updated} thread(s)")
    except Exception as e:  # noqa: BLE001
        log.warning(f"summarize_sessions skipped: {type(e).__name__}: {e}")
