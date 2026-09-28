import asyncio
from app.agent.model import reserve_call
from app.integrations.media import audio_wav
from app.modules.model_services.usage import RequestRecord
from app.tasks.lease import lease


async def prepare_transcripts(context, attachments, transcript, revision, provider=None):
    from sqlalchemy import select
    from app.modules.messages.models import Message
    from app.modules.messages.audio import joined_transcript
    from app.tasks.feedback import publish
    async with context.sessions() as db:
        live, _ = await lease(db, context)
        result = dict(live.result)
        message_id = live.target_id
    if transcript.strip():
        return transcript, revision, result
    audio = [item for item in attachments if item.kind == 'audio']
    if not audio:
        return transcript, revision, result
    parts = dict(result.get('audioTranscripts', {}))
    for attachment in audio:
        if attachment.id not in parts:
            await publish(context, 'transcribing', force=True)
            text = await (provider(context, attachment) if provider else asr(context, attachment))
            if not text or not text.strip():
                raise ValueError(f'语音“{attachment.name}”未识别出文字，请检查录音后重试或修正语音文字；其他材料已保留')
            parts[attachment.id] = {'name': attachment.name, 'text': text.strip()}
            async with context.sessions.begin() as db:
                live, _ = await lease(db, context)
                live.result = {**live.result, 'audioTranscripts': parts}
                result = dict(live.result)
    transcript = joined_transcript(result)
    async with context.sessions.begin() as db:
        await lease(db, context)
        message = await db.scalar(select(Message).where(Message.id == message_id).with_for_update())
        if message.transcript_revision == revision:
            message.transcript, message.transcript_revision = transcript, revision + 1
        # A correction entered during ASR wins over the generated transcript.
        return message.transcript, message.transcript_revision, result


async def asr(context, attachment):
    from app.modules.model_services.bindings import resolve_bound
    from app.integrations.models.asr import transcribe
    from app.integrations.models.transport import safe_error
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
