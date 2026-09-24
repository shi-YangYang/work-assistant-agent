from app.core.errors import problem
from app.db.base import now
from app.modules.auth.models import DesktopAuthorization
from app.modules.auth.sessions import digest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select


async def grant(db, identifier, *, lock=False):
    if len(identifier) != 43:
        problem(410, '授权已失效，请回到桌面重新连接', 'invalid_grant')
    query = select(DesktopAuthorization).where(DesktopAuthorization.request_hash == digest(identifier))
    item = await db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
    if item is None or item.expires_at <= now() or item.state in ('denied', 'consumed'):
        problem(410, '授权已失效，请回到桌面重新连接', 'invalid_grant')
    return item


NATIVE_WRITES = {'/api/v1/desktop/login/start', '/api/v1/desktop/login/exchange', '/api/v1/desktop/logout'}


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class Exchange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    verifier: str = Field(min_length=43, max_length=128, pattern=r'^[A-Za-z0-9._~-]+$')


class Approval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approve: bool


def identity_dto(actor, company, expires):
    return {'member': {'id': actor.id, 'name': actor.name, 'role': actor.role},
            'company': {'id': company.id, 'name': company.name}, 'expiresAt': expires.isoformat()}
