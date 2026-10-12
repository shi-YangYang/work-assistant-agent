"""Separate one browser's login retries from a shared office's request budget."""
import hashlib
import hmac
import re
import secrets
import time

from app.modules.auth.sessions import throttle
from app.security.secrets import read_key


RATE_COOKIE = 'paa_dingtalk_rate'
COOKIE_SECONDS = 3600
COOKIE_PATH = '/api/v1/auth/dingtalk'
TOKEN = re.compile(r'([A-Za-z0-9_-]{43})\.([0-9]{1,12})\.([0-9a-f]{64})')


def browser_token(value, settings):
    # Domain-separated MAC; this cookie is never used as login authorization.
    key = read_key(settings.model_key_file)
    instant = int(time.time())

    def signature(payload):
        return hmac.new(key, b'dingtalk-login-rate:v1:' + payload.encode(), hashlib.sha256).hexdigest()

    match = TOKEN.fullmatch(value) if len(value) <= 128 else None
    if match:
        identifier, issued, mac = match.groups()
        payload = identifier + '.' + issued
        if 0 <= instant - int(issued) < COOKIE_SECONDS and hmac.compare_digest(signature(payload), mac):
            return value, False
    payload = secrets.token_urlsafe(32) + '.' + str(instant)
    return payload + '.' + signature(payload), True


async def login_rate(request, response):
    settings = request.app.state.settings
    token, fresh = browser_token(request.cookies.get(RATE_COOKIE, ''), settings)
    host = request.client.host if request.client else 'unknown'
    # Commit the IP admission independently: cookie rotation and browser-level
    # rejection must not roll it back and bypass the shared-network protection.
    async with request.app.state.sessions.begin() as db:
        await throttle(db, 'dingtalk:login:ip:' + host, limit=120, window_seconds=60,
                       code='login_network_rate_limited', message='当前网络的登录请求较多，请稍后重试')
    async with request.app.state.sessions.begin() as db:
        await throttle(db, 'dingtalk:login:browser:' + token, limit=12,
                       code='login_browser_rate_limited', message='登录操作过于频繁，请稍后重试')
    if fresh:
        response.set_cookie(RATE_COOKIE, token, max_age=COOKIE_SECONDS, httponly=True,
                            secure=settings.cookie_secure, samesite='lax', path=COOKIE_PATH)
