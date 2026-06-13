from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from eventbuddy.domain.models import AuditLog


class AuditRepository:
    """Writes the authoritative record of every HITL-confirmed (or denied) action
    (architecture §11/§16). Only a *hash* of the payload is stored — never its contents
    (recipients/body), keeping PII out of the audit trail."""

    def __init__(self, session: Session):
        self.s = session

    @staticmethod
    def _hash(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def record(self, *, event_id: str | None, actor_user_id: str | None, action: str,
               tool_name: str | None, payload: dict, result: str) -> None:
        self.s.add(AuditLog(
            event_id=event_id,
            actor_user_id=actor_user_id,
            action=action,
            tool_name=tool_name,
            payload_hash=self._hash(payload),
            result=result,
        ))
