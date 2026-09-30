"""Attach cookies only after successful business responses and DB finalization."""
import asyncio
import logging

from app.db.base import now
from app.modules.auth.session_policy import ABSOLUTE_LIFETIME, renewal_due
from app.modules.auth.sessions import COOKIE, renew_session, set_session_cookie
from starlette.requests import Request
from starlette.responses import Response

renewal_log = logging.getLogger('uvicorn.error.paa_session_renewal')

# These existing reads also serve automatic polling or task recovery. Excluding
# them centrally prevents an unattended tab from counting as user activity.
BACKGROUND_READS = frozenset({
    '/api/v1/jobs/{identifier}',
    '/api/v1/jobs/{identifier}/events',
    '/api/v1/jobs/{identifier}/feedback',
    '/api/v1/conversations/{identifier}/active-job',
    '/api/v1/reports',
    '/api/v1/reports/{identifier}',
    '/api/v1/work-items/{identifier}',
    '/api/v1/report-obligations',
    '/api/v1/team/report-obligations',
    '/api/v1/notifications',
    '/api/v1/team/workspace/{view}',
    '/api/v1/business-sources/{message_id}/{token}',
    '/api/v1/work-items/{identifier}/business-sources/{token}',
    '/api/v1/settings/voiceprints',
})


def eligible(request, message):
    if not 200 <= message['status'] < 300 or not getattr(request.state, 'session', None):
        return False
    path = request.url.path
    if path.startswith('/api/v1/auth/') and path != '/api/v1/auth/me':
        return False
    route = getattr(request.scope.get('route'), 'path', '')
    if request.method in ('GET', 'HEAD') and route in BACKGROUND_READS:
        return False
    for name, value in message.get('headers', []):
        if name.lower() == b'content-type' and value.lower().startswith(b'text/event-stream'):
            return False
        if name.lower() == b'set-cookie' and value.decode('latin-1').split('=', 1)[0].strip() == COOKIE:
            return False
    return True


class SessionRenewal:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope, receive)

        async def renewed_send(message):
            if message['type'] == 'http.response.start' and eligible(request, message):
                try:
                    session = request.state.session
                    instant = now()
                    expires = min(session.expires_at, session.created_at + ABSOLUTE_LIFETIME)
                    if renewal_due(session.created_at, expires, instant):
                        async with asyncio.timeout(2):
                            expires = await renew_session(request.app.state.sessions, session)
                        if expires is not None:
                            # Only the short transaction can authorize a cookie;
                            # a throttled request's snapshot may have been revoked.
                            cookie = Response()
                            set_session_cookie(cookie, request.cookies[COOKIE], expires, request.app.state.settings)
                            message['headers'] = list(message.get('headers', [])) + [
                                header for header in cookie.raw_headers if header[0] == b'set-cookie'
                            ]
                except Exception as error:
                    # The business operation already succeeded. Never turn this
                    # best-effort renewal into a retry of a committed write.
                    renewal_log.warning('session renewal failed: %s', type(error).__name__)
            await send(message)

        await self.app(scope, receive, renewed_send)
