# tests/unit/test_ids.py
from eventbuddy.common.ids import new_id


def test_new_id_is_unique_uuid_string():
    a, b = new_id(), new_id()
    assert isinstance(a, str) and len(a) == 36
    assert a != b
