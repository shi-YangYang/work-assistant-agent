import asyncio
import logging
import signal
from .db import registry
from paa_server.core.config import Settings
from paa_server.db.session import database
from paa_server.tasks.maintenance import scheduler
from paa_server.tasks.runner import run_slots


async def main():
    settings = Settings()
    engine, sessions = database(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    # This deployment deliberately runs one bounded worker. A second process
    # exits instead of silently multiplying model requests and connections.
    from psycopg import AsyncConnection
    async with await AsyncConnection.connect(settings.checkpoint_url, autocommit=True) as guard:
        row = await (await guard.execute('SELECT pg_try_advisory_lock(17017)')).fetchone()
        if not row[0]:
            await engine.dispose()
            raise RuntimeError('A company worker is already running')
        timer = asyncio.create_task(scheduler(sessions, settings))
        from paa_server.tasks.voiceprints import worker_loop
        voiceprints = asyncio.create_task(worker_loop(sessions, settings, stop))
        try:
            await run_slots(sessions, settings, stop)
        finally:
            timer.cancel()
            voiceprints.cancel()
            await asyncio.gather(timer, voiceprints, return_exceptions=True)
            await engine.dispose()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
