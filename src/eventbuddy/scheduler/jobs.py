from eventbuddy.common.logging import get_logger

log = get_logger("scheduler.jobs")


def run_reminder(event_id: str, kind: str) -> None:
    # Live send wired once creds exist; logs prove the job fired.
    log.info(f"reminder fired event={event_id} kind={kind}")


def run_feedback_send(event_id: str) -> None:
    log.info(f"feedback_send fired event={event_id}")


def run_feedback_followup(event_id: str) -> None:
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
