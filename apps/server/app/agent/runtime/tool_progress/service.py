"""Lease-serialized progress, shared by discovery and actual execution nodes."""
import copy
import json
from langchain_core.messages import ToolMessage
from app.core.digests import digest
from app.tasks.lease import lease
from app.tasks.budget import service as budget
from . import research, state
from .evidence import WRITES, page_cursor, failed_result, completed_page, dependencies, exploratory_result, page_scope, payload, request_key, result_key, reusable_read, search_evidence, terminal_web_failure, web_address


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
    message = '本次未执行：相同操作已有结果、仍在执行或此范围已读完。使用已有回执；若结果未知先读取真实回执。只有新来源、版本或修正参数才有必要继续。'
    if call['name'] in ('web_search', 'web_fetch'):
        message = '本次未执行：相同操作已有结果、仍在执行或此范围已读完，请复用已有回执。'
    if decision == 'stop':
        message = '本次未执行。连续调用没有新进展，请直接交付已获得结果并说明未完成范围；不要复述内部限制。'
    if decision == 'research_stop':
        message = research.NOTICE
    return ToolMessage(tool_call_id=call['id'], name=call['name'], status='error', content=json.dumps({
        'state': 'not_executed', 'code': 'research_no_progress' if decision == 'research_stop' else 'tool_no_progress',
        'message': message,
    }, ensure_ascii=False))


async def begin(context, call):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        value = scoped(context, job)
        web = call['name'] in research.TOOLS
        identifier = call.get('progressId', call['id'])
        prior = next((row for row in value['calls'] if row['id'] == identifier), None)
        retained = value.get('research', {}).get('records', {}).get(identifier) if web else None
        prior = prior or retained
        research_closed = research.register(value, call) if web and prior is None else False
        research_blocked = research_closed and not research.cached_read(context, call)
        deps = dependencies(context, job, call)
        page = page_scope(call)
        cursor = call.get('args', {}).get(page_cursor(call) or '', 0)
        refreshing_work = call['name'] == 'get_work_item' and call.get('args', {}).get('work_id') in context.refresh_work_versions
        exhausted = bool(page and cursor and not refreshing_work and not call.get('args', {}).get('refresh') and value.get('pages', {}).get(page) == deps)
        request, address = request_key(call), web_address(call)
        last_address = next((row for row in reversed(value['calls']) if address and row.get('address', row.get('deniedAddress')) == address
                             and row.get('result') and row.get('executed') is not False and row['dependencies'] == deps), None)
        unavailable_address = bool(last_address and last_address.get('deniedAddress') == address)
        denied = value.get('research', {}).get('denied', {}).get(address)
        cached = research.cached_read(context, call)
        unavailable_address = unavailable_address and not cached
        refresh_denied = bool(denied) or unavailable_address and last_address.get('readError') in ('http_401', 'http_403', 'http_404', 'http_410', 'blocked_url', 'web_challenge')
        repeated_read = call['name'] in ('web_search', 'web_fetch', 'find_documents') and (not call.get('args', {}).get('refresh') or refresh_denied) and any(
            row.get('reusableRead') and (row['request'] == request and (not row.get('deniedAddress') or unavailable_address) or
                (row is last_address and unavailable_address)) and row['dependencies'] == deps
            for row in value['calls'])
        if retained:
            decision = retained['decision']
        else:
            value, decision = state.admit(value, identifier, request, deps,
                prevent_duplicate=call['name'] in WRITES | {'load_tools'}, exhausted=exhausted or repeated_read or bool(denied) and not cached or research_blocked,
                track_progress=not web)
        if research_blocked:
            decision = 'research_stop'
            value['calls'][-1]['decision'] = decision
        if web and decision != 'execute':
            research.complete(value, call, False)
        if web and not retained:
            row = next(row for row in value['calls'] if row['id'] == identifier)
            research.journal(value).setdefault('records', {})[identifier] = dict(row)
        if decision != 'execute':
            from app.tasks.streaming.lifecycle import source_snapshot, validate_sources
            from app.modules.messages.models import Message
            await validate_sources(db, actor, job, await db.get(Message, job.target_id), source_snapshot(context, job),
                                   refresh_work_versions=context.refresh_work_versions)
        persist(job, context, value)
        result = feedback(call, decision) if decision != 'execute' else None
        if result is not None and call.get('decisionId'):
            from app.agent.runtime.decision_flow import end as decision_end
            result = decision_end(context, job, call, result)
    return result


def with_feedback(message, result, fields):
    if fields and isinstance(message.content, str):
        # JSONB does not retain key order; keep the model's content string stable.
        fields = {key: fields[key] for key in ('newEvidenceCount', 'progressNotice') if key in fields}
        return message.model_copy(update={'content': json.dumps({**result, **fields}, ensure_ascii=False)})
    return message


async def end(context, call, message):
    result = payload(message)
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        value = scoped(context, job)
        deps = dependencies(context, job, call)
        identifier = call.get('progressId', call['id'])
        web = call['name'] in ('web_search', 'web_fetch')
        prior = next((row for row in value['calls'] if row['id'] == identifier), None)
        prior = prior or (value.get('research', {}).get('records', {}).get(identifier) if web else None)
        replay = bool(prior and prior.get('result'))
        if replay and web:
            # Node outputs precede this feedback. Replay the original additions,
            # never derive an old call's evidence count from later discoveries.
            projected = with_feedback(message, result, prior.get('webFeedback', {}))
            if call.get('decisionId'):
                from app.agent.runtime.decision_flow import end as decision_end
                projected = decision_end(context, job, call, projected)
            return projected
        no_progress = False
        new_evidence_count = None
        if call['name'] == 'web_search' and not failed_result(result) and message.status != 'error' and not replay:
            known = value.get('searchEvidence', [])
            current = search_evidence(result)
            new_evidence_count = len(set(current).difference(known))
            no_progress = new_evidence_count == 0
            value['searchEvidence'] = list(dict.fromkeys([*known, *current]))
        soft_stall = message.status != 'error' and exploratory_result(value, call, result, identifier, deps)
        value, warning = state.complete(value, identifier, result_key(call, result), deps, failed=failed_result(result) or message.status == 'error', executed=result.get('executed') is not False and result.get('state') != 'not_executed', no_progress=no_progress, soft_stall=soft_stall, track_progress=not web)
        if web:
            progress = bool(new_evidence_count)
            known = research.journal(value)['evidence']
            if message.status != 'error':
                links = research.link_evidence(result).difference(known)
                progress = progress or bool(links)
                known.extend(sorted(links))
            if call['name'] == 'web_fetch' and not failed_result(result) and message.status != 'error':
                evidence = research.page_evidence(result)
                new_text = bool(evidence and evidence not in known)
                progress = progress or new_text
                if new_text:
                    known.append(evidence)
            research.complete(value, call, progress)
            address = web_address(call)
            if address and terminal_web_failure(result):
                research.journal(value)['denied'][address] = {'code': result['errorCode']}
                failed_address = web_address({'name': 'web_fetch', 'args': {'url': result.get('failedUrl')}})
                if failed_address:
                    research.journal(value)['denied'][failed_address] = {'code': result['errorCode']}
        completed = next((row for row in value['calls'] if row['id'] == identifier), None)
        if completed is None and web:
            completed = value.get('research', {}).get('records', {}).get(identifier)
            if completed and not completed.get('result'):
                completed.update(result=result_key(call, result), dependencies=deps,
                                 executed=result.get('executed') is not False and result.get('state') != 'not_executed')
        if completed and not replay:
            completed['reusableRead'] = reusable_read(call, result) and message.status != 'error'
            address = web_address(call)
            if address:
                completed['address'] = address
                if completed['reusableRead'] and failed_result(result):
                    completed['deniedAddress'] = address
                    completed['readError'] = result.get('errorCode')
        page = page_scope(call)
        if page and not failed_result(result) and message.status != 'error':
            pages = dict(value.get('pages', {}))
            if completed_page(call, result):
                pages[page] = deps
            else:
                pages.pop(page, None)
            value['pages'] = dict(list(pages.items())[-state.HISTORY:])
        fields = {}
        if new_evidence_count is not None:
            fields['newEvidenceCount'] = new_evidence_count
        if warning or no_progress:
            if no_progress:
                notice = '本次搜索没有新增来源或摘要，已有结果仍有效。'
            elif soft_stall and failed_result(result):
                notice = '本次未取得网页正文，已有来源仍有效。'
            elif call['name'] == 'web_fetch':
                notice = '本次网页读取没有新增内容，已有来源仍有效。'
            else:
                notice = '此结果与已读信息相同。不要继续同样调用；修正已指出的参数、使用新的来源或直接答复。'
            fields['progressNotice'] = notice
        if completed and web:
            completed['webFeedback'] = fields
            research.journal(value).setdefault('records', {})[identifier] = dict(completed)
        persist(job, context, value)
        projected = with_feedback(message, result, fields)
        if call.get('decisionId'):
            from app.agent.runtime.decision_flow import end as decision_end
            projected = decision_end(context, job, call, projected)
    return projected


def research_stopped(context, job, messages=()):
    value = copy.deepcopy(scoped(context, job))
    if 'research' not in value:
        return False
    stopped = research.settle(value)
    persist(job, context, value)
    if stopped and research.rejected_batch(value, messages):
        # Research was already closed at the preceding model boundary. An
        # entirely rejected follow-up batch cannot make progress; use the
        # existing reserved final-answer path without another rejection loop.
        budget.finalize(job, context, 'no_progress')
    return stopped


async def web_cache(context, url=None):
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        closed = research_stopped(context, job)
        address = web_address({'name': 'web_fetch', 'args': {'url': url}})
        denied = scoped(context, job).get('research', {}).get('denied', {}).get(address)
    return research.SnapshotReader(context.web_pages) if closed or denied else context.web_pages
