# tests/unit/test_models.py
from eventbuddy.domain.models import (
    AuditLog,
    Document,
    Event,
    EventMember,
    FeedbackResponse,
    Report,
    ScheduledJob,
    Task,
)


def test_event_tablename_and_columns():
    assert Event.__tablename__ == "events"
    cols = set(Event.__table__.columns.keys())
    assert {"event_id", "event_name", "teams_channel_id", "status"} <= cols


def test_member_has_event_fk_and_unique():
    cols = set(EventMember.__table__.columns.keys())
    assert {"event_id", "teams_user_id", "role", "registration_status"} <= cols


def test_task_has_event_fk_and_status():
    cols = set(Task.__table__.columns.keys())
    assert {"event_id", "task_name", "assignee_id", "due_date", "status"} <= cols


def test_document_table_and_columns():
    assert Document.__tablename__ == "documents"
    assert {"doc_id", "event_id", "filename", "drive_item_id", "mime_type",
            "parse_status", "ingested_at"} <= set(Document.__table__.columns.keys())


def test_scheduled_job_table_and_columns():
    assert ScheduledJob.__tablename__ == "scheduled_jobs"
    assert {"job_id", "event_id", "job_type", "target", "channel",
            "scheduled_at", "status"} <= set(ScheduledJob.__table__.columns.keys())


def test_feedback_response_table_and_columns():
    assert FeedbackResponse.__tablename__ == "feedback_responses"
    assert {"response_id", "event_id", "respondent_id", "raw_payload",
            "sentiment", "themes", "submitted_at"} <= set(FeedbackResponse.__table__.columns.keys())


def test_report_table_and_columns():
    assert Report.__tablename__ == "reports"
    assert {"report_id", "event_id", "metrics_json", "summary_md",
            "suggestions_md", "generated_at"} <= set(Report.__table__.columns.keys())


def test_audit_log_table_and_columns():
    assert AuditLog.__tablename__ == "audit_log"
    assert {"log_id", "event_id", "actor_user_id", "action", "tool_name",
            "payload_hash", "result", "created_at"} <= set(AuditLog.__table__.columns.keys())
