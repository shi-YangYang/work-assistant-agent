"""Lease-serialized progress, shared by discovery and actual execution nodes."""
import json
from langchain_core.messages import ToolMessage
from app.core.digests import digest
from app.tasks.lease import lease
from app.tasks.budget import service as budget
from . import state
from .evidence import WRITES, page_cursor, failed_result, completed_page, dependencies, page_scope, payload, request_key, result_key


def scoped(context, job):
    scope = digest({'company': context.company_id, 'owner': context.owner_id, 'job': job.id,
                    'round': job.attempt, 'input': context.node_scope or context.source_revision})
    value = job.result.get('toolProgress', {})
    return value if value.get('version') == state.VERSION and value.get('scope') == scope else state.create(scope)


def persist(job, context, value):
    job.result = {**job.result, 'toolProgress': value}
    if value['stopped']:
        budget.finalize(job, context, 'no_progress')


def feedback(call, decision):
    return ToolMessage(tool_call_id=call['id'], name=call['name'], status='error', content=json.dumps({
        'state': 'not_executed', 'code': 'tool_no_progress',
        'message': '本次未执行：相同操作已有结果、仍在执行或此范围已读完。使用已有回执；若结果未知先读取真实回执。只有新来源、版本或修正参数才有必要继续。' if decision != 'stop' else '本次未执行。连续调用没有新进展，请直接交付已获得结果并说明未完成范围；不要复述内部限制。',
    }, ensure_ascii=False))


async def begin(context, call):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        value = scoped(context, job)
        deps = dependencies(context, job, call)
        page = page_scope(call)
        cursor = call.get('args', {}).get(page_cursor(call) or '', 0)
        refreshing_work = call['name'] == 'get_work_item' and call.get('args', {}).get('work_id') in context.refresh_work_versions
        exhausted = bool(page and cursor and not refreshing_work and not call.get('args', {}).get('refresh') and value.get('pages', {}).get(page) == deps)
        value, decision = state.admit(value, call.get('progressId', call['id']), request_key(call), deps,
            prevent_duplicate=call['name'] in WRITES | {'load_tools'}, exhausted=exhausted)
        if decision != 'execute':
            from app.tasks.streaming.lifecycle import source_snapshot, validate_sources
            from app.modules.messages.models import Message
            await validate_sources(db, actor, job, await db.get(Message, job.target_id), source_snapshot(context, job),
                                   refresh_work_versions=context.refresh_work_versions)
        persist(job, context, value)
    return feedback(call, decision) if decision != 'execute' else None


async def end(context, call, message):
    result = payload(message)
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        value = scoped(context, job)
        deps = dependencies(context, job, call)
        value, warning = state.complete(value, call.get('progressId', call['id']), result_key(call, result), deps, failed=failed_result(result) or message.status == 'error', executed=result.get('executed') is not False and result.get('state') != 'not_executed')
        page = page_scope(call)
        if page and not failed_result(result) and message.status != 'error':
            pages = dict(value.get('pages', {}))
            if completed_page(call, result):
                pages[page] = deps
            else:
                pages.pop(page, None)
            value['pages'] = dict(list(pages.items())[-state.HISTORY:])
        persist(job, context, value)
    if warning and isinstance(message.content, str):
        result['progressNotice'] = '此结果与已读信息相同。不要继续同样调用；修正已指出的参数、使用新的来源或直接答复。'
        return message.model_copy(update={'content': json.dumps(result, ensure_ascii=False)})
    return message
