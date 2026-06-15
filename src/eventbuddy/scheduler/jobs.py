from eventbuddy.common.logging import get_logger

log = get_logger("scheduler.jobs")


def _resolve_host_token(host_user_id: str | None) -> tuple[str | None, str]:
    """Background auth resolver (Plan 13). Returns `(token, status)`:
      • app-only (no OAuth connection) → `(None, "ok")` — `graph_for()` uses the app creds;
      • delegated + host has a valid stored token → `(token, "ok")` — act as the host;
      • delegated + host not signed in / token expired → `(None, "reauth")` — the job degrades
        and the host must re-open EventBuddy to re-authenticate.
    Best-effort: never raises (token fetch is wrapped)."""
    from eventbuddy.integrations.graph.delegated import (
        acquire_graph_token_for_user,
        delegated_enabled,
    )
    if not delegated_enabled():
        return None, "ok"
    token = acquire_graph_token_for_user(host_user_id) if host_user_id else None
    return (token, "ok") if token else (None, "reauth")


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
        host_id = ev.host_user_id
        recipients = [m.email for m in MemberRepository(s).list(event_id) if m.email]

    if not _graph_creds():
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(event_id=event_id, job_type=kind, status="failed")
        log.warning(f"reminder {kind} for {event_id}: Graph not configured — skipped")
        return 0

    # Plan 13 — under delegated auth the send acts as the event host (the token service stores
    # the host's refresh token). No valid host token → the host must re-authenticate; the job
    # degrades rather than crashing (matching the no-creds path).
    host_token, status = _resolve_host_token(host_id)
    if status == "reauth":
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(event_id=event_id, job_type=kind, status="failed")
        log.warning(f"reminder {kind} for {event_id}: host not signed in — needs re-auth, skipped")
        return 0

    from eventbuddy.agent.wiring import graph_for
    from eventbuddy.integrations.graph.delegated import use_graph_token

    with use_graph_token(host_token):  # None under app-only → graph_for uses app creds
        graph = graph_for()
        if graph is None:
            with session_scope() as s:
                ScheduledJobRepository(s).set_status(
                    event_id=event_id, job_type=kind, status="failed")
            log.warning(f"reminder {kind} for {event_id}: Graph unavailable — skipped")
            return 0
        svc = ReminderService(graph)
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


def _send_form_individually(event_name: str, form_link: str, emails: list[str], graph) -> int:
    """Mail the Forms link to each recipient one-by-one (never a shared To/CC — PII §11). The
    `graph` is resolved by the caller (delegated host token under Plan 13, or app-only)."""
    from eventbuddy.capabilities.feedback import FeedbackDispatchService

    svc = FeedbackDispatchService(graph)
    for email in emails:
        svc.send_form(event_name=event_name, form_link=form_link, member_emails=[email])
    return len(emails)


def _dispatch_form_as_host(event_id: str, job_type: str, event_name: str, form_link: str,
                           emails: list[str], host_id: str | None) -> int | None:
    """Send the feedback form to `emails` acting as the event host (Plan 13). Returns the count
    sent, or None when degraded (host re-auth needed / Graph unavailable) — setting the job
    status to 'failed' in that case. Never raises."""
    from eventbuddy.agent.wiring import graph_for
    from eventbuddy.data.db import session_scope
    from eventbuddy.data.repositories.scheduled_jobs import ScheduledJobRepository
    from eventbuddy.integrations.graph.delegated import use_graph_token

    host_token, status = _resolve_host_token(host_id)
    if status == "reauth":
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(
                event_id=event_id, job_type=job_type, status="failed")
        log.warning(f"{job_type} for {event_id}: host not signed in — needs re-auth, skipped")
        return None
    with use_graph_token(host_token):  # None under app-only → graph_for uses app creds
        graph = graph_for()
        if graph is None:
            with session_scope() as s:
                ScheduledJobRepository(s).set_status(
                    event_id=event_id, job_type=job_type, status="failed")
            log.warning(f"{job_type} for {event_id}: Graph unavailable — skipped")
            return None
        return _send_form_individually(event_name, form_link, emails, graph)


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
        host_id = ev.host_user_id
        event_form_url = ev.feedback_form_url  # per-event link (Option 1) wins
        emails = [m.email for m in MemberRepository(s).list(event_id) if m.email]

    form_link = event_form_url or _feedback_form_link(event_id)
    if not form_link or not _graph_creds():
        with session_scope() as s:
            ScheduledJobRepository(s).set_status(
                event_id=event_id, job_type="feedback_send", status="failed")
        log.warning(f"feedback_send for {event_id}: form link / Graph not configured — skipped")
        return 0

    n = _dispatch_form_as_host(event_id, "feedback_send", event_name, form_link, emails, host_id)
    if n is None:
        return 0  # degraded (host re-auth / Graph unavailable) — status already set
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
        host_id = ev.host_user_id
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

    n = _dispatch_form_as_host(
        event_id, "feedback_followup", event_name, form_link, non_responders, host_id)
    if n is None:
        return 0  # degraded (host re-auth / Graph unavailable) — status already set
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


def run_summarize_sessions() -> None:
    """Periodic rolling-summary consolidation (Phase 1.7). Best-effort: a failure (e.g. no
    DB/LLM creds) must not crash the scheduler.

    The summarizer is rebuilt here at fire time rather than captured as a job arg: a
    persistent (SQLAlchemy) jobstore pickles each job's args, and the live summarizer holds
    an unpicklable ``threading.RLock`` via its LLM client. Reconstructing per run keeps the
    persisted job a bare picklable function reference."""
    try:
        from eventbuddy.agent.wiring import build_summarizer
        summarizer = build_summarizer()
        if summarizer is None:
            return
        updated = summarizer.summarize_all()
        if updated:
            log.info(f"summarize_sessions updated {updated} thread(s)")
    except Exception as e:  # noqa: BLE001
        log.warning(f"summarize_sessions skipped: {type(e).__name__}: {e}")
