from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from .config import Settings


def database(settings: Settings):
    engine = create_async_engine(settings.database_url, pool_size=2, max_overflow=1, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
