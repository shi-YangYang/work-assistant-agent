import asyncio
from paa_server.agent.model import reserve_call
from paa_server.integrations.media import audio_wav
from paa_server.modules.model_services.usage import RequestRecord
from paa_server.tasks.lease import lease


async def asr(context, attachment):
    from paa_server.modules.model_services.bindings import resolve_bound
    from paa_server.integrations.models.asr import transcribe
    from paa_server.integrations.models.transport import safe_error
    settings = context.settings
    wav, _ = await audio_wav(settings.media_dir / attachment.id, settings)
    usage_id = await reserve_call(context, 'asr')
    record = RequestRecord(context.sessions, usage_id)
    try:
        async with context.sessions() as db:
            await lease(db, context)
            config, key = await resolve_bound(db, settings, context.company_id, context.model_binding or {}, 'asr')
        transcript, usage = await record.run(lambda event: asyncio.wait_for(transcribe(settings, config, key, wav, on_event=event), 60))
    except Exception as error:
        await record.finish(error)
        raise safe_error(error) from None
    return transcript
