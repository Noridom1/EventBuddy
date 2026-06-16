import json

from eventbuddy.common.logging import configure_logging, get_logger


def test_configure_logging_emits_valid_json(capsys):
    configure_logging()
    get_logger("test").warning('message with "quotes" and \n newline')
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)  # must not raise
    assert parsed["level"] == "WARNING"
    assert parsed["logger"] == "test"


def test_formatter_passes_structured_extras(capsys):
    """Impl 10 — whitelisted structured fields ride into the JSON line; a plain log is
    unchanged (no stray keys)."""
    configure_logging()
    get_logger("agent.trace").info(
        "llm.input",
        extra={"event": "llm.input", "thread_id": "dm:u1", "step": 2,
               "payload": [{"role": "human", "content": "hi"}]},
    )
    get_logger("test").info("plain message")
    lines = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln]
    traced = json.loads(lines[0])
    assert traced["event"] == "llm.input"
    assert traced["thread_id"] == "dm:u1"
    assert traced["step"] == 2
    assert traced["payload"] == [{"role": "human", "content": "hi"}]

    plain = json.loads(lines[1])
    assert plain == {"level": "INFO", "logger": "test", "msg": "plain message"}
