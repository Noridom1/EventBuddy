"""Phase 1.8 — ToolNode error classification.

`_handle_tool_error` decides what happens when a tool fails inside the agent loop:
- a **tool-usage error** (bad args/values — the model's fault) is handed back so the model
  can correct its call and retry;
- **anything else** is a system/config failure a retry can't fix, so the model gets clean
  guidance to relay to the user (no retry, no regex fallback).

`caused_by` walks the exception chain because LangChain wraps an argument-validation failure
in `ToolInvocationError`, nesting the real `ValidationError` under `__cause__`."""
from pydantic import BaseModel, ValidationError

from eventbuddy.agent.errors import RETRYABLE, ToolUsageError, caused_by
from eventbuddy.agent.runner import _SYSTEM_ERROR_GUIDANCE, _handle_tool_error


def _validation_error() -> ValidationError:
    """A real Pydantic ValidationError, like the one a bad tool argument produces."""
    class _M(BaseModel):
        recipients: list[str]

    try:
        _M(recipients="a@x.com")  # str where a list is required
    except ValidationError as e:
        return e
    raise AssertionError("expected a ValidationError")


# ── classification: model's fault → retry guidance ───────────────────────────────────────
def test_validation_error_is_retryable():
    out = _handle_tool_error(_validation_error())
    assert "Fix the arguments" in out
    assert out != _SYSTEM_ERROR_GUIDANCE


def test_tool_usage_error_is_retryable():
    out = _handle_tool_error(ToolUsageError("bad value"))
    assert "bad value" in out
    assert "Fix the arguments" in out


def test_wrapped_validation_error_is_retryable():
    # Mirrors LangChain's ToolInvocationError wrapping: the ValidationError is the __cause__.
    try:
        raise RuntimeError("Error invoking tool 'send_outlook_mail'") from _validation_error()
    except RuntimeError as wrapped:
        out = _handle_tool_error(wrapped)
    assert "Fix the arguments" in out


# ── classification: system/config failure → clean no-retry message ───────────────────────
def test_runtime_error_is_system_failure():
    out = _handle_tool_error(RuntimeError("Graph API 503"))
    assert out == _SYSTEM_ERROR_GUIDANCE


def test_connection_error_is_system_failure():
    out = _handle_tool_error(ConnectionError("db unreachable"))
    assert out == _SYSTEM_ERROR_GUIDANCE


# ── caused_by chain walking ──────────────────────────────────────────────────────────────
def test_caused_by_finds_nested_cause():
    err = _validation_error()
    wrapped = RuntimeError("outer")
    wrapped.__cause__ = err
    assert caused_by(wrapped, RETRYABLE)


def test_caused_by_false_for_unrelated_chain():
    assert not caused_by(RuntimeError("nope"), RETRYABLE)


def test_caused_by_survives_a_self_referential_cycle():
    # Defensive: a cyclic __context__ must not loop forever.
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__context__ = b
    b.__context__ = a
    assert not caused_by(a, RETRYABLE)
