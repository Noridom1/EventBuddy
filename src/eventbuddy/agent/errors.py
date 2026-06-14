"""Agent error taxonomy — classifies a tool failure so the loop knows what the model
may retry versus what it must not.

Two tiers reach the ToolNode error handler ([runner.py]):
- **Tool-usage errors** — the model called a tool wrong (bad arg type/shape/value).
  Pydantic raises `ValidationError`; a tool body may raise `ToolUsageError` for a bad
  value. These are handed back to the loop so the model corrects its call and retries.
- **Everything else** — a system/config failure the model can't fix by retrying. The
  handler returns a clean, no-retry message the model relays to the user instead.

Config gaps that are *expected* (no Graph creds, no bound channel) should still be handled
at the capability boundary by returning a friendly string (see wiring.py) — those never
raise, so they never reach this taxonomy at all."""


class ToolUsageError(Exception):
    """A tool was called with bad arguments/values the model can fix. Safe to surface
    back to the loop for a corrected retry."""


# Exceptions the model can resolve by re-calling the tool with corrected arguments.
RETRYABLE: tuple[type[BaseException], ...]

try:  # pydantic is always present, but keep the import local to this module's concern
    from pydantic import ValidationError

    RETRYABLE = (ValidationError, ToolUsageError)
except ImportError:  # pragma: no cover - pydantic is a hard dependency
    RETRYABLE = (ToolUsageError,)


def caused_by(exc: BaseException, types: tuple[type[BaseException], ...]) -> bool:
    """True if `exc` or anything in its cause/context chain is an instance of `types`.

    LangChain wraps a tool's argument-validation failure in `ToolInvocationError`, so the
    real `ValidationError` is nested — walk `__cause__`/`__context__` to find it."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, types):
            return True
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return False
