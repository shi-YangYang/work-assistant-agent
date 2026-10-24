"""Changed data domains retain actual personal and team source read paths."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.agent.runtime import decision_flow as flow
from app.security.access import remember, scope
from app.tasks.models import Job
from test_decision_followups import begin, end, state


def source(job, actor, kind, identifier, *, parent=None, **extra):
    evidence = {'type': kind, 'id': identifier, 'ownerId': 'employee', 'version': 1,
                **({'parent': parent} if parent else {})}
    token = remember(job, actor, evidence)
    return {'kind': 'business', 'token': token, 'objectType': kind, 'objectId': identifier,
            'ownerId': 'employee', 'revision': 1, **extra}


@pytest.mark.parametrize('family', ['work', 'report'])
def test_team_reads_follow_only_returned_same_domain_sources_and_declared_children(family):
    context, job = state()
    actor = SimpleNamespace(id='admin', company_id='company', role='admin')
    job.access = scope(actor)
    write, _ = begin(context, job, 'execute_business_action', 'delete', {'action': 'delete_' + family, 'target_id': 'gone'})
    end(context, job, write, {'state': 'succeeded', 'id': 'operation', 'action': 'delete_' + family})
    metadata = {'after': write['decisionId'], 'need': '查询剩余记录并读取其原始材料'}
    wrong_family = 'report' if family == 'work' else 'work'
    assert begin(context, job, 'query_team_business', 'other-domain', {'kind': wrong_family}, metadata)[1] is not None
    first = source(job, actor, family, 'remaining')
    previous = source(job, actor, family, 'previous-read')
    wrong = source(job, actor, wrong_family, 'different-domain')
    query, denied = begin(context, job, 'query_team_business', 'query', {'kind': family}, metadata)
    assert denied is None
    # A result from another family and a body's token do not extend this scope.
    end(context, job, query, {'items': [first, wrong], 'content': {'token': previous['token']}, 'nextCursor': 'page2'})
    for token in [previous['token'], wrong['token'], 'invented']:
        assert begin(context, job, 'read_team_source', token, {'token': token}, metadata)[1] is not None
    detail, denied = begin(context, job, 'read_team_source', 'detail', {'token': first['token']}, metadata)
    assert denied is None
    assert begin(context, job, 'read_team_source', 'early-child', {'token': first['token'], 'child_id': 'message'}, metadata)[1] is not None
    end(context, job, detail, {**first, 'sourceMessageIds': ['message']})
    child_args = {'token': first['token'], 'child_id': 'message'}
    child, denied = begin(context, job, 'read_team_source', 'child', child_args, metadata)
    assert denied is None
    message = source(job, actor, 'message', 'message', parent=job.access['reads'][first['token']],
                     attachments=[{'id': 'document', 'kind': 'document'}, {'id': 'image', 'kind': 'image'}])
    end(context, job, child, message)
    assert begin(context, job, 'read_team_source', 'image', {'token': message['token'], 'child_id': 'image'}, metadata)[1] is not None
    assert begin(context, job, 'read_team_source', 'unlisted', {'token': message['token'], 'child_id': 'secret'}, metadata)[1] is not None
    document_args = {'token': message['token'], 'child_id': 'document'}
    document = source(job, actor, 'document', 'document', parent=job.access['reads'][message['token']])
    for start in (0, 1):
        read, denied = begin(context, job, 'read_team_source', 'page-' + str(start), {**document_args, 'start': start}, metadata)
        assert denied is None
        end(context, job, read, document)
        job.result = json.loads(json.dumps(job.result))
    assert begin(context, job, 'read_team_source', 'document-token', {'token': '[[business:' + document['token'] + ']]'}, metadata)[1] is None
    assert begin(context, job, 'query_team_business', 'next-page', {'kind': family, 'cursor': 'page2'}, metadata)[1] is None
    flow.finish(context, job)
    assert begin(context, job, 'read_team_source', 'finished', document_args, metadata)[1] is not None


@pytest.mark.parametrize('mismatch', ['access', 'owner', 'revision', 'parent'])
def test_team_result_cannot_invent_authority_or_reparent_sources(mismatch):
    context, job = state()
    actor = SimpleNamespace(id='admin', company_id='company', role='admin')
    job.access = scope(actor)
    write, _ = begin(context, job, 'execute_business_action', 'delete', {'action': 'delete_report', 'target_id': 'gone'})
    end(context, job, write, {'state': 'succeeded', 'id': 'operation', 'action': 'delete_report'})
    metadata = {'after': write['decisionId'], 'need': '读取剩余报告'}
    item = source(job, actor, 'report', 'remaining')
    if mismatch == 'access':
        item['token'] = 'not-in-job-access'
    elif mismatch == 'owner':
        item['ownerId'] = 'other-company-owner'
    elif mismatch == 'revision':
        item['revision'] = 2
    query, _ = begin(context, job, 'query_team_business', 'query', {'kind': 'report'}, metadata)
    end(context, job, query, {'items': [item]})
    if mismatch != 'parent':
        assert begin(context, job, 'read_team_source', 'read', {'token': item['token']}, metadata)[1] is not None
        return
    detail, _ = begin(context, job, 'read_team_source', 'detail', {'token': item['token']}, metadata)
    end(context, job, detail, {**item, 'sourceMessageIds': ['message']})
    child, _ = begin(context, job, 'read_team_source', 'child', {'token': item['token'], 'child_id': 'message'}, metadata)
    unrelated = source(job, actor, 'message', 'message', parent={'type': 'work', 'id': 'other-work'})
    end(context, job, child, unrelated)
    assert begin(context, job, 'read_team_source', 'wrong-parent', {'token': unrelated['token']}, metadata)[1] is not None


async def actual_read(context, job, tool, key, args, metadata=None):
    call, denied = begin(context, job, tool.name, key, args, metadata)
    assert denied is None
    result = json.loads(await tool.coroutine(runtime=SimpleNamespace(context=context), **args))
    async with context.sessions() as db:
        job.access = (await db.get(Job, context.job_id)).access
    end(context, job, call, result)
    return call, result


@pytest.mark.asyncio
async def test_obligation_directory_opens_only_actual_report_links_without_inventing_versions(setup):
    from app.agent.tools.business.actions import query_report_obligations, query_reports
    from app.db.base import now
    from app.modules.reports.models import ReportObligation
    from _support.agent.execution_permissions import mode_runtime
    from _support.work.team_workspace import report
    _, sessions, users, _ = setup
    async with sessions.begin() as db:
        linked = await report(db, users['employee'], '2026-09-01', published=False)
        cancelled = await report(db, users['employee'], '2026-08-24', published=False)
        for item, status in [(linked, 'pending'), (cancelled, 'cancelled')]:
            db.add(ReportObligation(company_id=item.company_id, owner_id=item.owner_id,
                kind='weekly', period=item.period, period_end=item.period_end, timezone=item.timezone,
                rule_revision=1, generate_at=now(), deadline_at=now(), reminders=False,
                before_minutes=30, state=status, report_id=item.id))
        await report(db, users['peer'], '2026-09-01')
    context, _ = await mode_runtime(setup, 'full', '修改报告后查看剩余汇报待办和对应草稿')
    job = SimpleNamespace(result={})
    value = flow.current(context, job)
    value['phase'] = 'executing'
    flow.save(job, value)
    write, _ = begin(context, job, 'execute_business_action', 'write', {'action': 'edit_report', 'target_id': 'changed'})
    end(context, job, write, {'state': 'succeeded', 'id': 'operation', 'action': 'edit_report',
                            'objectType': 'report', 'objectId': 'changed', 'objectRevision': 2})
    metadata = {'after': write['decisionId'], 'need': '查看剩余汇报待办对应的报告内容'}
    _, listing = await actual_read(context, job, query_report_obligations, 'obligations', {}, metadata)
    assert {item['reportId'] for item in listing['items']} == {linked.id, None}
    assert context.read_versions == {}
    for identifier in [cancelled.id, *(item['id'] for item in listing['items'])]:
        assert begin(context, job, 'query_reports', 'not-report-' + identifier, {'report_id': identifier}, metadata)[1] is not None
    _, detail = await actual_read(context, job, query_reports, 'report', {'report_id': linked.id}, metadata)
    assert detail['items'][0]['id'] == linked.id and detail['items'][0]['revision'] == linked.revision
    assert context.read_versions == {linked.id: linked.revision}


@pytest.mark.asyncio
async def test_admin_delete_then_team_pages_source_documents_and_live_version_checks(setup):
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.agent.actions.operations import execute
    from app.agent.tools.business.actions import query_reports
    from app.agent.tools.business.team import query_team_business, read_team_source
    from app.modules.attachments.models import Attachment, DocumentChunk
    from app.modules.reports.models import Report, ReportRevision
    from _support.agent.business_assistant import facts
    from _support.agent.execution_permissions import mode_runtime
    from _support.work.team_workspace import report
    _, sessions, users, _ = setup
    _, work_revision, original = await facts(sessions, users['employee'])
    async with sessions.begin() as db:
        reports = [await report(db, users['employee'], (date(2026, 9, 1) + timedelta(weeks=index)).isoformat()) for index in range(22)]
        revision = await db.scalar(select(ReportRevision).where(ReportRevision.report_id == reports[1].id))
        revision.source_ids = [work_revision.id]
        await report(db, users['outsider'], '2026-09-01')
        await report(db, users['peer'], '2026-09-01', published=False)
        attachment = Attachment(company_id=original.company_id, owner_id=original.owner_id, message_id=original.id,
            kind='document', name='原始材料.txt', mime='text/plain', size=12, sha256='a' * 64,
            extraction_status='ready', extraction_revision=1, extraction_info={'chunks': 2})
        db.add(attachment)
        await db.flush()
        for ordinal in (0, 1):
            db.add(DocumentChunk(company_id=original.company_id, owner_id=original.owner_id, attachment_id=attachment.id,
                revision=1, ordinal=ordinal, location=str(ordinal), text='原始第 ' + str(ordinal)))
    context, _ = await mode_runtime(setup, 'full', '删除报告 ' + reports[0].id + '，然后查看剩余报告及其原始材料', 'admin')
    job = SimpleNamespace(result={}, access={})
    read, result = await actual_read(context, job, query_reports, 'target', {'report_id': reports[0].id})
    args = {'step': 1, 'action': 'delete_report', 'target_id': reports[0].id, 'expected_revision': result['items'][0]['revision']}
    write, denied = begin(context, job, 'execute_business_action', 'delete', args, {'ready': [read['decisionId']]})
    assert denied is None and flow.current(context, job)['phase'] == 'executing'
    result = await execute(context, **args)
    assert result['state'] == 'succeeded', result
    end(context, job, write, result)
    metadata = {'after': write['decisionId'], 'need': '查看删除后剩余员工报告及其原始材料'}
    _, listing = await actual_read(context, job, query_team_business, 'remaining', {'kind': 'report'}, metadata)
    assert listing['total'] == 21 and len(listing['items']) == 20
    shown = {item['token'] for item in listing['items']}
    unseen = set(job.access['reads']) - shown
    assert len(unseen) == 1
    assert begin(context, job, 'read_team_source', 'not-shown', {'token': next(iter(unseen))}, metadata)[1] is not None
    _, page = await actual_read(context, job, query_team_business, 'page', {'kind': 'report', 'cursor': listing['nextCursor']}, metadata)
    assert len(page['items']) == 1 and not page['nextCursor']
    all_items = listing['items'] + page['items']
    assert {item['objectId'] for item in all_items} == {row.id for row in reports[1:]}
    assert '不能泄露' not in json.dumps(all_items, ensure_ascii=False)
    item = next(row for row in all_items if row['objectId'] == reports[1].id)
    _, detail = await actual_read(context, job, read_team_source, 'detail', {'token': item['token']}, metadata)
    assert detail['sourceMessageIds'] == [original.id]
    _, message = await actual_read(context, job, read_team_source, 'original', {'token': item['token'], 'child_id': original.id}, metadata)
    assert message['content']['text'] == original.text
    for start in (0, 1):
        _, document = await actual_read(context, job, read_team_source, 'document-' + str(start),
            {'token': message['token'], 'child_id': attachment.id, 'start': start}, metadata)
        assert document['content']['text'] == '原始第 ' + str(start)
    # Scope permits only a source pointer; the unchanged live authorization
    # boundary still rejects stale extraction versions before content is read.
    async with sessions.begin() as db:
        assert (await db.get(Report, reports[0].id)).deleted
        (await db.get(Attachment, attachment.id)).extraction_revision = 2
    _, denied = begin(context, job, 'read_team_source', 'stale', {'token': document['token']}, metadata)
    assert denied is None
    with pytest.raises(HTTPException) as error:
        await read_team_source.coroutine(token=document['token'], runtime=SimpleNamespace(context=context))
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('who,name,mode', [('employee', 'propose_progress', 'auto'), ('admin', 'propose_followup', 'full'), ('employee', 'propose_progress', 'ask')])
async def test_real_suggestion_effect_receipt_is_committed_stable_and_not_pending(setup, who, name, mode):
    from app.agent.tools.business.work import propose_progress, find_work_items
    from app.agent.tools.business.team import propose_followup, query_team_business
    from app.modules.work.models import WorkItem
    from _support.agent.business_assistant import facts
    from _support.agent.execution_permissions import mode_runtime
    context, _ = await mode_runtime(setup, mode, '记录一项跟进工作，然后列出剩余工作', who)
    invoke = SimpleNamespace(context=context)
    args = {'title': '跟进报价', 'summary': '核对报价', 'status': 'in_progress', 'blocker': '', 'next_step': '明天询问'}
    if name == 'propose_followup':
        await facts(setup[1], setup[2]['employee'])
        queried = json.loads(await query_team_business.coroutine(runtime=invoke))
        args['source_tokens'] = [queried['items'][0]['token']]
        await find_work_items.coroutine(query='', runtime=invoke)
    tool = propose_progress if name == 'propose_progress' else propose_followup
    job = SimpleNamespace(result={})
    value = flow.current(context, job)
    value['phase'] = 'executing'
    flow.save(job, value)
    write, _ = begin(context, job, name, 'save', args)
    result = json.loads(await tool.coroutine(runtime=invoke, **args))
    end(context, job, write, result)
    metadata = {'after': write['decisionId'], 'need': '列出剩余工作'}
    query, denied = begin(context, job, 'find_work_items', 'remaining', {'query': ''}, metadata)
    if mode == 'ask':
        assert result['state'] == 'pending' and 'objectId' not in result
        assert denied is not None
        return
    assert result['state'] == 'succeeded' and result['status'] == 'confirmed'
    assert result['objectType'] == 'work' and result['objectRevision'] == 1
    assert denied is None
    listed = json.loads(await find_work_items.coroutine(query='', runtime=invoke))
    assert [item['id'] for item in listed['items']] == [result['objectId']]
    end(context, job, query, listed)
    async with context.sessions.begin() as db:
        saved = await db.get(WorkItem, result['objectId'])
        saved.revision = 2
    context.suggestion_items.clear()
    context.suggestion_options.clear()
    replay, _ = begin(context, job, name, 'replay', args)
    repeated = json.loads(await tool.coroutine(runtime=invoke, **args))
    end(context, job, replay, repeated)
    assert repeated['objectId'] == result['objectId'] and repeated['objectRevision'] == 1
    assert not flow.current(context, job)['calls'][replay['decisionId']].get('changes')
    assert begin(context, job, 'find_work_items', 'old-receipt', {'query': ''}, metadata)[1] is not None
