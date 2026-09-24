import asyncio
import json
import time
from app.db.base import now
from app.integrations.models.asr import transcribe
from app.integrations.models.chat import chat
from app.integrations.models.samples import image_sample
from app.integrations.models.transport import ProviderError, safe_error
from app.modules.model_services.models import ModelCheck, ModelService, ModelServiceRevision, ModelUsage
from app.security.secrets import decrypt
from pathlib import Path
from sqlalchemy import select


async def reserve_probe(sessions, settings, actor, choice=None):
    async with sessions.begin() as db:
        from app.modules.model_services.usage import usage_fields
        usage = ModelUsage(company_id=actor.company_id, owner_id=actor.id, job_id=None, kind='admin_test', **usage_fields(choice))
        db.add(usage)
        await db.flush()
        return usage.id


async def probe(request_db, sessions, settings, actor, body, config, key, fingerprint):
    started = time.monotonic()
    result = {'draftVersion': body.draftVersion, 'fingerprint': fingerprint, 'service': body.name, 'model': config['model'] if config else '', 'revision': body.expectedRevision, 'purpose': body.purpose, 'time': now().isoformat(), 'checks': [], 'usage': None}
    names = ['语音转写'] if body.purpose == 'asr' else (['文字', '图片', '工具往返'] if body.purpose == 'assistant' else ['文字', '报告结构'])
    result['checks'] = [{'name': name, 'state': 'untested'} for name in names]
    current = 0
    totals = {'inputTokens': 0, 'outputTokens': 0}
    known_usage = False
    async def request_key():
        if not body.serviceId:
            return key
        # Read scalar columns on the existing request connection so each call
        # sees committed revocations without cached ORM rows or extra pool use.
        # A later edit keeps this revision valid; never resolve the latest one.
        credential = await request_db.scalar(select(ModelServiceRevision.credential).join(ModelService, ModelService.id == ModelServiceRevision.service_id).where(
            ModelService.id == body.serviceId,
            ModelService.company_id == actor.company_id,
            ModelService.revoked.is_(False),
            ModelServiceRevision.company_id == actor.company_id,
            ModelServiceRevision.revision == body.expectedRevision,
        ))
        if not credential:
            raise ProviderError('revoked', '本次检测引用的模型服务已撤销，请重新选择服务')
        saved_key = decrypt(settings.model_key_file, credential, actor.company_id, body.serviceId, body.expectedRevision)
        return key if body.apiKey else saved_key

    from app.modules.model_services.usage import RequestRecord
    choice = {'serviceId':body.serviceId, 'name':body.name or '未保存配置', 'model':config['model'] if config else None}
    async def request(messages, **kw):
        nonlocal known_usage
        usage_id = await reserve_probe(sessions, settings, actor, choice)
        record = RequestRecord(sessions, usage_id)
        try:
            outgoing_key = await request_key()
            response = await record.run(lambda event: asyncio.wait_for(chat(settings, config, outgoing_key, messages, max_tokens=256, on_event=event, **kw), 60))
        except BaseException as error:
            await record.finish(error)
            raise
        usage = response.get('usage') or {}
        if usage:
            known_usage = True
            totals['inputTokens'] += int(usage.get('prompt_tokens', 0))
            totals['outputTokens'] += int(usage.get('completion_tokens', 0))
        return response['choices'][0]['message']
    try:
        if not config or ((body.purpose == 'asr') != (config['protocol'] != 'chat')):
            raise ProviderError('protocol', '请选择适用于当前用途的模型协议')
        if body.purpose == 'asr':
            usage_id = await reserve_probe(sessions, settings, actor, choice)
            record = RequestRecord(sessions, usage_id)
            try:
                speech = (Path(__file__).parents[2] / 'assets/probe-zh.wav').read_bytes()
                outgoing_key = await request_key()
                transcript, usage = await record.run(lambda event: asyncio.wait_for(transcribe(settings, config, outgoing_key, speech, on_event=event), 60))
            except BaseException as error:
                await record.finish(error)
                raise
            cleaned = ''.join(c for c in transcript if c.isalnum())
            if not all(word in cleaned for word in ('今天', '工作', '完成')):
                raise ProviderError('invalid_response', '语音接口返回了文字，但未识别固定中文样本的主要内容')
            result['checks'][0]['state'] = 'passed'
            result['usage'] = usage
        else:
            answer = await request([{'role': 'user', 'content': '这是连通性测试。只回复：测试成功'}])
            if '测试成功' not in (answer.get('content') or ''):
                raise ProviderError('invalid_response', '模型没有按要求完成文字样本')
            result['checks'][current]['state'] = 'passed'; current += 1
            if body.purpose == 'assistant':
                answer = await request([{'role': 'user', 'content': [{'type': 'text', 'text': '这张图片是什么颜色？只回答颜色。'}, {'type': 'image_url', 'image_url': {'url': image_sample()}}]}])
                if '红' not in (answer.get('content') or ''):
                    raise ProviderError('invalid_response', '模型未正确识别固定图片，不能确认图片能力')
                result['checks'][current]['state'] = 'passed'; current += 1
            if body.purpose == 'report':
                answer = await request([{'role': 'user', 'content': '报告格式测试：返回 JSON 对象，字段 completed、ongoing、blockers、next 均为字符串，completed 填写“已完成测试”，其余为空。不要调用工具。'}])
                from langchain_core.messages import AIMessage
                from app.modules.reports.parsing import parse_report
                parse_report(AIMessage(content=answer.get('content') or ''))
            else:
                tools = [{'type': 'function', 'function': {'name': 'probe_echo', 'description': 'Return the supplied value for this capability test; no business writes.', 'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value'], 'additionalProperties': False}}}]
                messages = [{'role': 'user', 'content': '调用 probe_echo，value 为 测试成功，然后根据工具返回值只回答测试成功。'}]
                answer = await request(messages, tools=tools, tool_choice={'type': 'function', 'function': {'name': 'probe_echo'}})
                calls = answer.get('tool_calls') or []
                if len(calls) != 1 or calls[0]['function']['name'] != 'probe_echo' or json.loads(calls[0]['function']['arguments']) != {'value': '测试成功'}:
                    raise ProviderError('invalid_response', '模型没有返回所要求的完整工具调用')
                messages += [answer, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': '测试成功'}]
                answer = await request(messages, tools=tools)
                if answer.get('tool_calls') or '测试成功' not in (answer.get('content') or ''):
                    raise ProviderError('invalid_response', '模型没有根据工具结果完成回复')
            result['checks'][current]['state'] = 'passed'
    except Exception as error:
        failure = safe_error(error)
        result['checks'][current].update(state='failed', code=failure.code, message=str(failure), status=failure.status)
    result['elapsedMs'] = round((time.monotonic() - started) * 1000)
    if known_usage:
        result['usage'] = totals
    async with sessions.begin() as db:
        db.add(ModelCheck(company_id=actor.company_id, actor_id=actor.id, fingerprint=fingerprint, result=result))
    return result
