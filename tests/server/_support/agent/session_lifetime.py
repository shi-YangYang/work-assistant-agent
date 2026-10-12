"""Shared controlled fixtures extracted from test_session_lifetime."""
from http.cookies import SimpleCookie
from sqlalchemy import select
from app.modules.auth.models import Session
from app.modules.auth.sessions import COOKIE, digest


def freeze(monkeypatch, instant):
    for module in ('app.modules.auth.sessions', 'app.http.session_renewal',
                   'app.http.dependencies', 'app.modules.auth.desktop_router',
                   'app.tasks.feedback.feedback'):
        monkeypatch.setattr(module + '.now', lambda: instant)


async def stored(sessions, client):
    async with sessions() as db:
        return await db.scalar(select(Session).where(Session.token_hash == digest(client.cookies.get(COOKIE))))


async def age_session(sessions, client, created_at, expires_at):
    async with sessions.begin() as db:
        record = await db.scalar(select(Session).where(Session.token_hash == digest(client.cookies.get(COOKIE))))
        record.created_at, record.expires_at = created_at, expires_at
        return record


def cookie(response):
    result = SimpleCookie()
    for header in response.headers.get_list('set-cookie'):
        result.load(header)
    return result.get(COOKIE)
