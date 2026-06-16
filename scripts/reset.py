"""Hard reset EventBuddy to a clean slate — wipes EVERYTHING, both datastores.

Unlike the dev `/api/dev/reset` route (which clears only the conversation-memory stack —
working windows, transcript, summaries, focused-event sessions), this drops **all** state:

  • Postgres — every table: events, members, tasks, documents, scheduled_jobs, feedback,
    reports, audit_log, AND the memory tables (conversation_messages, session_summaries).
  • Redis — every working window (LangGraph checkpoints), every focused-event session, and
    any stray per-thread locks.

Operates on whatever ``DATABASE_URL`` / ``REDIS_URL`` are configured — i.e. the SAME cloud
datastores a deployed AgentBase runtime reads. So `make reset` from your laptop wipes the
*live* demo state. Destructive and irreversible — prompts for confirmation unless ``--yes``.

Degrades gracefully (matching the rest of the app): a missing/unreachable datastore is
reported and skipped rather than aborting the whole reset.

Usage:
    venv/bin/python scripts/reset.py [--yes]
"""
import argparse
import sys

from sqlalchemy import text

# Import the models module so every table is registered on Base.metadata before we truncate.
import eventbuddy.domain.models  # noqa: F401
from eventbuddy.config import settings
from eventbuddy.data.db import Base, engine


def _wipe_database() -> int:
    """TRUNCATE every mapped table in one statement (CASCADE handles FK order). Returns the
    number of tables cleared, or -1 if the DB was unreachable."""
    tables = list(Base.metadata.sorted_tables)
    if not tables:
        return 0
    names = ", ".join(t.name for t in tables)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    except Exception as e:  # noqa: BLE001 — report and skip, don't abort the whole reset
        print(f"  ! database wipe failed ({type(e).__name__}: {e})")
        return -1
    return len(tables)


def _wipe_redis() -> dict:
    """Clear the conversation working windows + focused-event sessions (+ stale locks). Returns
    per-bucket counts. No-op (zeros) when no Redis is configured."""
    cleared = {"windows": 0, "sessions": 0, "locks": 0}
    if not settings.redis_url:
        print("  - no REDIS_URL configured; skipping Redis")
        return cleared

    from eventbuddy.agent.memory import build_checkpointer, flush_all_windows
    from eventbuddy.agent.session import SessionStore
    from eventbuddy.data.redis import get_redis

    try:
        cleared["windows"] = flush_all_windows(build_checkpointer())
        client = get_redis()
        cleared["sessions"] = SessionStore(client).clear_all()
        for key in client.scan_iter(match="lock:*", count=500):
            cleared["locks"] += client.delete(key)
    except Exception as e:  # noqa: BLE001 — best-effort, never raise mid-reset
        print(f"  ! Redis wipe partially failed ({type(e).__name__}: {e})")
    return cleared


def reset(assume_yes: bool = False) -> None:
    print("This will PERMANENTLY wipe ALL EventBuddy state:")
    print(f"  • Postgres : {settings.database_url.split('@')[-1]}")
    print(f"  • Redis    : {'(none configured)' if not settings.redis_url else 'configured'}")
    if not assume_yes:
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("aborted")
            sys.exit(1)

    print("Resetting…")
    n_tables = _wipe_database()
    if n_tables >= 0:
        print(f"  ✓ database — truncated {n_tables} table(s)")
    redis_counts = _wipe_redis()
    print(
        f"  ✓ redis — {redis_counts['windows']} window(s), "
        f"{redis_counts['sessions']} session(s), {redis_counts['locks']} lock(s)"
    )
    print("Done. Clean slate. (Re-seed demo data with `make seed`.)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Hard-reset EventBuddy (DB + Redis).")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = p.parse_args()
    reset(assume_yes=args.yes)
