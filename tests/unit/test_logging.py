import json

from eventbuddy.common.logging import configure_logging, get_logger


def test_configure_logging_emits_valid_json(capsys):
    configure_logging()
    get_logger("test").warning('message with "quotes" and \n newline')
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)  # must not raise
    assert parsed["level"] == "WARNING"
    assert parsed["logger"] == "test"
