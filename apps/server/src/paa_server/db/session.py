from paa_server.core.config import Settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def database(settings: Settings):
    engine = create_async_engine(settings.database_url, pool_size=2, max_overflow=1, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
