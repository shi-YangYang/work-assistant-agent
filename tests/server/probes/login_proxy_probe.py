"""Disposable HTTP probe; never used by the production app entry point."""
import os

import httpx
from fastapi import Request
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.integrations.dingtalk import DingTalkProvider
from app.main import create_app
from _support.http.dingtalk import OfficialResponses

settings = Settings()
if os.getenv('PAA_TEST_LOGIN_PROXY') != '1' or make_url(settings.database_url).database != 'paa_company_test':
    raise RuntimeError('Login probe requires the dedicated test database and explicit opt-in')

app = create_app(settings)
app.state.dingtalk_provider = DingTalkProvider(httpx.MockTransport(OfficialResponses()))


@app.get('/api/v1/test/client')
async def client(request: Request):
    return {'host': request.client.host, 'scheme': request.url.scheme}
