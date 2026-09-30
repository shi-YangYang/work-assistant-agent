from zoneinfo import ZoneInfo
"""Task recovery and complete, authorized context across tool/job boundaries."""
import io
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from PIL import Image
from sqlalchemy import select

from app.agent.actions.operations import execute
from app.agent.tools.actions import query_reports
from app.agent.tools.documents import read_document
from app.agent.tools.messages import get_message_context
from app.agent.tools.team import find_team_members, query_team_business
from app.agent.tools.work import get_work_item
from app.db.base import now
from app.modules.attachments.models import Attachment
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.reports.models import Report
from app.modules.reports.service import ensure_report
from app.modules.work.models import WorkItem
from app.tasks.processing.documents import prepare_document
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job
from app.tasks.nodes.node_execution import execute_node
from app.tasks.runtime.queue import claim
from test_business_actions import Judge, create, finish, runtime
from test_company import keyed, send
from test_documents import running_context, upload
from test_management import conversation, message
from test_report_reliability import ReportModel

pytestmark = pytest.mark.asyncio


class Review:
    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        return AIMessage(content=json.dumps({'issues': []}))


async def test_identical_copies_are_distinct_but_each_copy_replays_once(setup):
    _, sessions, users, _ = setup
    context, _ = await runtime(setup, '创建两条完全相同的客户回访工作，分别保存。')
    args = {'action': 'create_work', 'changes': {'title': '客户回访', 'summary': '询问后续需求'}}
    first = await execute(context, step=1, **args)
    second = await execute(context, step=2, copy_index=2, **args)
    for step, copy, expected in [(1, 1, first), (2, 2, second), (3, 1, first)]:
        repeated = await execute(context, step=step, copy_index=copy, **args)
        assert repeated['id'] == expected['id']
    assert first['objectId'] != second['objectId']
    async with sessions() as db:
        items = (await db.scalars(select(WorkItem).where(WorkItem.owner_id == users['employee'].id))).all()
        assert len(items) == 2
    assert context.intent_model.inputs[-1]['proposedOperation']['copyIndex'] == 2


async def test_another_copy_needs_its_own_authorization(setup):
    _, sessions, users, _ = setup
    context, _ = await runtime(setup, '只创建一条客户回访')
    args = {'action': 'create_work', 'changes': {'title': '客户回访'}}
    assert (await execute(context, step=1, **args))['state'] == 'succeeded'
    context.intent_model = Judge(allowed=False)
    denied = await execute(context, step=2, copy_index=2, **args)
    assert denied['state'] == 'clarification'
    assert len(context.intent_model.inputs) == 1
    async with sessions() as db:
        assert len((await db.scalars(select(WorkItem).where(WorkItem.owner_id == users['employee'].id))).all()) == 1


async def test_unrequested_write_is_skipped_without_marking_readonly_task_incomplete(setup, monkeypatch):
    from app.agent.runtime.tool_nodes import outcome
    from langchain_core.messages import ToolMessage
    from test_business_actions import run_reply
    class ReferenceOnlyJudge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            return AIMessage(content=json.dumps({'allowed': False, 'notRequested': True, 'quote': payload['currentUserText'], 'reason': '本轮只记住，不创建'}))
    async def graph(context, *args, **kwargs):
        context.intent_model = ReferenceOnlyJudge()
        result = await execute(context, step=1, action='create_work', changes={'title': '备用工作'})
        assert result['state'] == 'not_requested'
        assert outcome(ToolMessage(content=json.dumps(result), tool_call_id='extra'))[0] == 'cancelled'
        from fakes import set_delivery
        await set_delivery(context, '已记下，等待下一条请求。', business=True)
        return '已记下，等待下一条请求。'
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    data = await run_reply(setup, '先记住，暂不创建：备用工作', '', Review())
    assert not data['actions'] and not data['job']['incompleteTask']
    assert not data['job']['operationFeedback']
    assert '已记下' in data['reply']


async def test_complete_work_and_paged_message_preserve_tail(setup):
    item = await create(setup[3]['employee'], '长工作', summary='概' * 4000, blocker='阻' * 1900, nextStep='计' * 1900 + '关键尾部')
    context, sent = await runtime(setup, '甲' * 7000 + '必须保留的尾部要求')
    work = json.loads(await get_work_item.coroutine(item['id'], SimpleNamespace(context=context)))
    assert '关键尾部' in json.dumps(work, ensure_ascii=False)
    parts, offset = [], 0
    for _ in range(6):
        page = json.loads(await get_message_context.coroutine(sent['messageId'], SimpleNamespace(context=context), start=offset))
        assert len(page['text']) <= 1500
        parts.append(page['text'])
        offset = page['nextContentOffset']
        if offset is None:
            break
    assert ''.join(parts) == '甲' * 7000 + '必须保留的尾部要求'


@pytest.mark.parametrize('change_model,change_work', [(False, True), (True, False), (True, True)])
async def test_retry_refreshes_stale_reply_and_tool_reads(setup, monkeypatch, change_model, change_work):
    from test_model_services import create as create_service, route, payload
    settings, sessions, users, clients = setup
    service = await create_service(clients['admin'])
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=route(service))).status_code == 200
    work = await create(clients['employee'], '当前状态', status='in_progress')
    sent = await send(clients['employee'], '核验这项工作是否已经完成')
    calls = []
    async def graph(context, *args, **kwargs):
        calls.append(context.node_scope)
        async def read():
            return await get_work_item.coroutine(work['id'], SimpleNamespace(context=context))
        evidence = await execute_node(context, identity='read-work', kind='tool', label='读取工作', operation=read)
        context.reply_evidence = [{'id': 0, 'tool': 'get_work_item', 'result': evidence}]
        from fakes import set_delivery
        await set_delivery(context, '最新状态：' + json.loads(evidence)['status'])
        context.delivery.update(verification_requested=True, verification_quote='核验这项工作是否已经完成')
        return '最新状态：' + json.loads(evidence)['status']
    class BrokenReview:
        async def ainvoke(self, messages):
            raise RuntimeError('controlled interruption')
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=BrokenReview())
    first = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert first['job']['state'] == 'awaiting_retry', first
    if change_work:
        edited = await clients['employee'].post('/api/v1/work-items/' + work['id'] + '/progress', json={'expectedRevision': 1, 'title': '当前状态', 'status': 'done'})
        assert edited.status_code == 200, edited.text
    if change_model:
        changed = await clients['admin'].patch('/api/v1/settings/model-services/' + service['id'], json={**payload(), 'expectedRevision': 1, 'apiKey': ''})
        assert changed.status_code == 200, changed.text
    assert (await clients['employee'].post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={})).status_code == 200
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=Review())
    last = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(calls) == 2 and calls[0] != calls[1]
    assert last['job']['state'] == 'awaiting_input', last
    assert ('done' if change_work else 'in_progress') in last['reply']


async def test_admin_own_creation_after_team_history_is_not_rejected(setup):
    _, sessions, _, clients = setup
    await create(clients['employee'], '员工项目')
    previous, sent = await runtime(setup, '查看团队工作', who='admin')
    await query_team_business.coroutine(SimpleNamespace(context=previous))
    async with sessions.begin() as db:
        old = await db.get(Message, sent['messageId'])
        old.access = (await db.get(Job, previous.job_id)).access
        old.reply = '员工项目正在推进。'
    await finish(previous)
    context, _ = await runtime(setup, '另外创建我自己的工作：整理个人桌面，与员工项目无关。', who='admin')
    result = await execute(context, step=1, action='create_work', changes={'title': '整理个人桌面'})
    assert result['state'] == 'succeeded', result
    # Permissions are still inherited; removing the source cannot make it public.
    async with sessions() as db:
        saved = await db.get(WorkItem, result['objectId'])
        assert saved.owner_id == context.owner_id and saved.access.get('team')


async def test_explicit_reference_keeps_late_instruction(setup):
    from app.agent.context.conversation_context import conversation_references
    _, sessions, users, clients = setup
    previous, sent = await runtime(setup, '甲' * 3500 + '具体要求：标题必须写成海棠项目。')
    await finish(previous)
    result = await clients['employee'].post('/api/v1/messages', json={'text': '按这条消息末尾的要求创建工作。', 'replyTo': sent['messageId']}, headers=keyed())
    assert result.status_code == 202
    job = await claim(sessions, users['employee'].id)
    async with sessions.begin() as db:
        refs = await conversation_references(db, users['employee'], await db.get(Job, job.id), await db.get(Message, job.target_id))
    assert refs[0]['explicitReplyTarget'] and '海棠项目' in refs[0]['userText']
    assert refs[0]['userText'] == '甲' * 3500 + '具体要求：标题必须写成海棠项目。'
    assert 'userText' not in refs[0].get('truncatedFields', [])


async def test_report_list_is_bounded_and_full_content_is_retrievable(setup):
    _, sessions, users, clients = setup
    reports = []
    for offset in range(2):
        async with sessions.begin() as db:
            report, _ = await ensure_report(db, users['employee'], 'daily', now().date() - timedelta(days=offset))
        content = {'completed': '甲' * 8000, 'ongoing': '乙' * 7999 + '末'}
        saved = await clients['employee'].patch('/api/v1/reports/' + report.id, json={'expectedRevision': 1, 'content': content})
        assert saved.status_code == 200, saved.text
        reports.append(report)
    context, _ = await runtime(setup, '读最近两份日报')
    call = SimpleNamespace(context=context)
    raw = await query_reports.coroutine(call)
    assert len(raw) < 6500
    listing = json.loads(raw)
    assert len(listing['items']) == 2 and all(item['contentTruncated'] for item in listing['items'])
    parts, offset = [], 0
    for _ in range(8):
        page = json.loads(await query_reports.coroutine(call, report_id=reports[0].id, content_start=offset))['items'][0]
        parts.append(page['content']['ongoing'])
        offset = page['nextContentOffset']
        if offset is None:
            break
    assert ''.join(parts) == content['ongoing']


async def test_member_directory_cursor_covers_all_authorized_members(setup):
    _, sessions, users, _ = setup
    async with sessions.begin() as db:
        for index in range(20):
            db.add(Member(company_id=users['admin'].company_id, username='page_' + users['admin'].id[:8] + str(index), name='目录员工' + str(index), role='employee', password_hash=users['employee'].password_hash))
    context, _ = await runtime(setup, '列出全部员工姓名', who='admin')
    first = json.loads(await find_team_members.coroutine('', SimpleNamespace(context=context)))
    second = json.loads(await find_team_members.coroutine('', SimpleNamespace(context=context), cursor=first['nextCursor']))
    ids = [item['id'] for page in (first, second) for item in page['items']]
    assert first['total'] == 22 and len(set(ids)) == 22
    assert not second['hasMore'] and second['nextCursor'] is None
    assert users['outsider'].id not in ids and users['admin'].id not in ids
    context, _ = await runtime(setup, '列出员工姓名', who='employee')
    denied = await find_team_members.coroutine('', SimpleNamespace(context=context), cursor=20)
    assert users['peer'].id not in denied


@pytest.mark.parametrize('change', ['', 'before', 'during'])
async def test_report_gets_read_document_requirements_and_rechecks_them(setup, change):
    settings, sessions, users, clients = setup
    await create(clients['employee'], '项目验收', summary='验收已完成', status='done')
    conv = await conversation(clients['employee'])
    marker = '每项先结论后依据，末尾加上质检清单。'
    attached = await upload(clients['employee'], '报告要求.txt', marker.encode(), 'text/plain')
    sent = await message(clients['employee'], conv, '按附件要求生成今天日报，不提交。', [attached['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    context.intent_model = Judge()
    await prepare_document(context, attached['id'])
    await read_document.coroutine(attached['id'], 0, SimpleNamespace(context=context))
    result = await execute(context, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    assert result['state'] == 'running', result
    await finish(context)
    async def mutate():
        async with sessions.begin() as db:
            (await db.get(Attachment, attached['id'])).extraction_revision += 1
    if change == 'before':
        await mutate()
    class Model(ReportModel):
        async def ainvoke(self, messages):
            answer = await super().ainvoke(messages)
            if change == 'during' and self.inputs:
                await mutate()
            return answer
    model = Model()
    job = await claim(sessions, users['employee'].id)
    await process_job(job, sessions, settings, None, model=model)
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert bool(live.result.get('reportSaved')) is (not change), live.error
        if change:
            assert not any((await db.get(Report, job.target_id)).content.values())
    if change != 'before':
        for request in (model.inputs[0], model.reviews[0]):
            assert marker in json.dumps(json.loads(request[-1].content)['materialsForInstructionsOnly'], ensure_ascii=False)


@pytest.mark.parametrize('explicit', [False, True])
async def test_image_followup_carries_pixels_and_stays_inside_conversation(setup, monkeypatch, explicit):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    raw = io.BytesIO()
    Image.new('RGB', (100, 100), color='red').save(raw, format='PNG')
    image = await upload(clients['employee'], '上张图.png', raw.getvalue(), 'image/png')
    first = await message(clients['employee'], conv, '先看这张图', [image['id']])
    seen = []
    async def graph(context, saver, content, model, **kwargs):
        seen.append(content)
        from fakes import set_delivery
        await set_delivery(context, '可以继续提问。')
        return '可以继续提问。'
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    async def process():
        await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=Review())
    await process()
    await message(clients['employee'], conv, '刚才那张图背景什么颜色？', **({'replyTo': first['messageId']} if explicit else {}))
    await process()
    assert sum(item['type'] == 'image_url' for item in seen[1]) == 1
    assert '"historical": true' in seen[1][0]['text']
    other = await conversation(clients['employee'])
    await message(clients['employee'], other, '你好')
    await process()
    assert not any(item['type'] == 'image_url' for item in seen[2])


async def test_removed_historical_image_stops_reply_save(setup, monkeypatch):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    raw = io.BytesIO()
    Image.new('RGB', (2, 2)).save(raw, format='PNG')
    image = await upload(clients['employee'], '旧图.png', raw.getvalue(), 'image/png')
    await message(clients['employee'], conv, '图片', [image['id']])
    first_job = await claim(sessions, users['employee'].id)
    async with sessions.begin() as db:
        (await db.get(Job, first_job.id)).state = 'succeeded'
    sent = await message(clients['employee'], conv, '再看一下图')
    async def graph(*args, **kwargs):
        async with sessions.begin() as db:
            (await db.get(Attachment, image['id'])).deleted = True
        return '不应保存此回答'
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=Review())
    saved = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert not saved['reply'] and saved['job']['state'] in ('failed', 'awaiting_retry')
