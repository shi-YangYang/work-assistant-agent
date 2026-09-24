import hashlib
import json
from paa_server.core.errors import problem
from paa_server.db.base import Base, Owned
from paa_server.modules.members.models import Member
from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


async def idem_begin(db, actor, action, key, payload):
    if not key or len(key) > 100:
        problem(422, '缺少有效的操作编号')
    from paa_server.security.locks import company_lock
    await company_lock(db, actor.company_id)
    # Serializes all writes for this identity, including repeat concurrent requests.
    await db.scalar(select(Member).where(Member.id == actor.id).with_for_update())
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    existing = await db.scalar(select(Idempotency).where(Idempotency.company_id == actor.company_id, Idempotency.owner_id == actor.id, Idempotency.action == action, Idempotency.key == key))
    if existing:
        if existing.digest != digest:
            problem(409, '同一操作编号不能用于不同内容')
        return existing.response, digest
    return None, digest


def idem_save(db, actor, action, key, digest, response):
    db.add(Idempotency(company_id=actor.company_id, owner_id=actor.id, action=action, key=key, digest=digest, response=response))
    return response


class Idempotency(Owned, Base):
    __tablename__ = 'company_idempotency'
    action: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('owner_id', 'action', 'key'),)
