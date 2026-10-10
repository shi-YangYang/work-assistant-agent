"""FastAPI application composition; business endpoints live in modules."""
import logging
from .core.config import Settings
from .db import registry
from .db.session import database
from .http.errors import http_error, model_error, validation_error
from .http.middleware import BodyLimit, Boundaries
from .http.session_renewal import SessionRenewal
from .http.routers import register_routes
from .integrations.dingtalk import DingTalkProvider
from .integrations.models.transport import ProviderError
from .security.secrets import SecretUnavailable
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError



def create_app(settings=None):
    settings = settings or Settings()
    engine, sessions = database(settings)

    @asynccontextmanager
    async def lifespan(app):
        settings.media_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        yield
        from app.tasks.streaming.redis_store import close_stores
        await close_stores()
        await engine.dispose()

    timing_log = logging.getLogger('paa.latency')
    timing_log.setLevel(logging.INFO)
    if not timing_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        timing_log.addHandler(handler)
    app = FastAPI(title='Company Work Assistant', version='0.1.0', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.sessions = sessions
    app.state.settings = settings
    app.state.dingtalk_provider = DingTalkProvider()
    app.add_middleware(BodyLimit)
    app.add_middleware(SessionRenewal)
    app.add_middleware(Boundaries)
    logging.getLogger('uvicorn.access').disabled = True
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(ProviderError, model_error)
    app.add_exception_handler(SecretUnavailable, model_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    register_routes(app)
    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
