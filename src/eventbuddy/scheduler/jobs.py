from eventbuddy.common.logging import get_logger

log = get_logger("scheduler.jobs")


def run_reminder(event_id: str, kind: str) -> None:
    # Live send wired once creds exist; logs prove the job fired.
    log.info(f"reminder fired event={event_id} kind={kind}")


def run_feedback_send(event_id: str) -> None:
    log.info(f"feedback_send fired event={event_id}")


def run_feedback_followup(event_id: str) -> None:
    log.info(f"feedback_followup fired event={event_id}")
