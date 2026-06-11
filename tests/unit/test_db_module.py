# tests/unit/test_db_module.py
from eventbuddy.data import db


def test_db_exposes_base_and_session_factory():
    # Base is the declarative base all models inherit; SessionLocal builds sessions.
    assert hasattr(db, "Base")
    assert hasattr(db, "SessionLocal")
    assert callable(db.SessionLocal)
