import asyncio
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from paa_server.db.base import now
from paa_server.modules.members.models import Member
from paa_server.modules.model_services.usage import interrupt_usage
from paa_server.security.locks import company_lock as business_company_lock
from paa_server.tasks.feedback_state import update_feedback
from paa_server.tasks.handlers import log, process_job
from paa_server.tasks.models import Job
from paa_server.tasks.queue import claim, interrupted_state
from sqlalchemy import select


async def worker_slot(sessions, settings, stop, *, saver_factory=None, runner=process_job):
    factory = saver_factory or (lambda: AsyncPostgresSaver.from_conn_string(settings.checkpoint_url))
    async with factory() as saver:
        while not stop.is_set():
            job = None
            try:
                job = await claim(sessions)
                if job:
                    await runner(job, sessions, settings, saver)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), 1)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                if job:
                    async with sessions.begin() as db:
                        await business_company_lock(db, job.company_id)
                        await db.scalar(select(Member).where(Member.id == job.owner_id).with_for_update())
                        live = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
                        if live.state == 'running' and live.fence == job.fence:
                            await interrupt_usage(db, live)
                            live.state = await interrupted_state(db, live)
                            if live.state == 'queued':
                                live.request_started = False
                            live.error = '处理已中断，请确认后重试' if live.state == 'awaiting_retry' else ''
                            live.fence, live.lease_until, live.updated_at = live.fence + 1, None, now()
                            update_feedback(live)
                raise
            except Exception as error:
                log.warning('worker slot failure_type=%s', type(error).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), 1)
                except asyncio.TimeoutError:
                    pass


async def run_slots(sessions, settings, stop, *, saver_factory=None, runner=process_job, shutdown_timeout=10):
    tasks = [asyncio.create_task(worker_slot(sessions, settings, stop, saver_factory=saver_factory, runner=runner)) for _ in range(settings.worker_concurrency)]
    try:
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
        if stop_task not in done:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            for task in done:
                task.result()
            raise RuntimeError('Worker processing slot exited unexpectedly')
        await asyncio.wait(tasks, timeout=shutdown_timeout)
    finally:
        if 'stop_task' in locals() and not stop_task.done():
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
