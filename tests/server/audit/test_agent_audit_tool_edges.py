"""Only genuine Spec059 matrix gaps; controlled IO, unchanged product paths."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from deepagents.backends.utils import create_file_data
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sqlalchemy import func, select

from app.agent.harness import build_graph
from app.agent.tools.business.actions import query_report_obligations
from app.agent.tools.business.team import find_team_members
from app.db.base import now
from app.modules.reports.models import ReportObligation
from app.modules.work.models import WorkItem
from _support.http.agent_audit_api import evidence
from _support.agent.fakes import completion
from _support.agent.agent_budget_flow import provider, response, run
from _support.agent.business_actions import finish, runtime
from _support.agent.completion_repair_boundary import MislabelledReadModel
from _support.agent.response_delivery import DeliveryModel, run as run_model

pytestmark = pytest.mark.asyncio


async def test_member_directory_invalid_cursor_and_employee_forgery(setup):
    admin, _ = await runtime(setup, '列出公司成员', 'admin')
    rows = []
    for cursor in (-1, 501):
        result = json.loads(await find_team_members.coroutine('', SimpleNamespace(context=admin), cursor))
        assert result == {'error': {'message': '员工分页位置无效', 'code': 'invalid_request'}}, result
        rows.append({'cursor': cursor, 'result': result})
    await finish(admin)
    employee, _ = await runtime(setup, '列出公司成员')
    denied = json.loads(await find_team_members.coroutine('', SimpleNamespace(context=employee)))
    assert 'error' in denied and 'items' not in denied
    assert '不能查询团队业务' in json.dumps(denied, ensure_ascii=False)
    evidence('member-tool-invalid-cursor', {'invalid': rows, 'employee': denied})


async def test_obligation_tool_pages_all_own_rows_and_rejects_invalid_period(setup):
    _, sessions, users, _ = setup
    expected = []
    async with sessions.begin() as db:
        for actor, count in ((users['employee'], 43), (users['peer'], 2)):
            for index in range(count):
                day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
                row = ReportObligation(company_id=actor.company_id, owner_id=actor.id, kind='daily',
                    period=day, period_end=day, timezone='Asia/Shanghai', rule_revision=1,
                    generate_at=now(), deadline_at=now() + timedelta(days=1), reminders=False, before_minutes=0)
                db.add(row)
                await db.flush()
                if actor.id == users['employee'].id:
                    expected.append(row.id)
    context, _ = await runtime(setup, '查我的应汇报历史')
    offset, actual, pages = 0, [], []
    while True:
        result = json.loads(await query_report_obligations.coroutine(SimpleNamespace(context=context), cursor=offset))
        assert result['counts']['expected'] == 43
        assert all(row['ownerId'] == users['employee'].id for row in result['items'])
        assert len(result['items']) <= 20
        actual.extend(row['id'] for row in result['items'])
        pages.append({'cursor': offset, 'count': len(result['items']), 'next': result['nextCursor']})
        if result['nextCursor'] is None:
            break
        assert int(result['nextCursor']) > offset
        offset = int(result['nextCursor'])
    assert len(actual) == len(set(actual)) == 43 and set(actual) == set(expected)
    invalid = await query_report_obligations.coroutine(SimpleNamespace(context=context), period='not-a-date')
    assert invalid == '汇报查询条件无效，请核对日期和范围。'
    evidence('obligation-tool-pages', {'pages': pages, 'ownCount': len(actual), 'foreignExcluded': 2, 'invalid': invalid})


class PagedVirtualModel(DeliveryModel):
    pages: list = Field(default_factory=list)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if isinstance(messages[-1], ToolMessage) and messages[-1].name == 'read_file':
            self.pages.append(messages[-1].content)
        if self.calls <= 3:
            answer = AIMessage(content='', tool_calls=[{'name': 'read_file', 'id': f'read-{self.calls}',
                'args': {'file_path': '/long.txt', 'offset': (self.calls - 1) * 20, 'limit': 20}}])
        else:
            answer = completion('已读取完整60行。')
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def test_virtual_file_offset_pages_reconstruct_all_lines(setup):
    context, _ = await runtime(setup, '分页读取本任务临时文件')
    model = PagedVirtualModel(model='controlled', api_key='unused')
    graph = build_graph(setup[0], None, context, model)
    state = await graph.ainvoke({'messages': [HumanMessage(content='分页读取本任务临时文件')],
        'files': {'/long.txt': create_file_data('\n'.join(f'UNIQUE_{index:03d}' for index in range(60))) }}, context=context)
    reads = [m for m in state['messages'] if isinstance(m, ToolMessage) and m.name == 'read_file']
    assert len(reads) == 3
    for page, message in enumerate(reads):
        expected = [f'UNIQUE_{index:03d}' for index in range(page * 20, (page + 1) * 20)]
        assert all(value in message.content for value in expected)
        assert message.content.count('UNIQUE_') == 20
    evidence('virtual-file-pages', {'pages': [m.content for m in reads], 'lines': 60})


@pytest.mark.parametrize('loop', ['catalog', 'same_url'])
async def test_forced_catalog_or_same_url_loops_stop_at_real_default_budget(setup, monkeypatch, loop):
    calls, requested, network = [], [], []
    if loop == 'same_url':
        from app.integrations import web_research
        original = web_research.web_fetch
        def page(request):
            network.append(str(request.url))
            return httpx.Response(200, headers={'content-type': 'text/plain'}, text='固定页面，没有新增内容。')
        async def fetch(url, **kwargs):
            return await original(url, transport=httpx.MockTransport(page), **kwargs)
        monkeypatch.setattr(web_research, 'web_fetch', fetch)
    async def chat(settings, config, key, messages, **kwargs):
        calls.append(True)
        if not kwargs.get('tools'):
            return response('<!--noria:{"remaining":["无新增信息，停止重复"]}-->\n本轮没有新增资料，已停止查询。')
        if loop == 'catalog':
            name, args = 'load_tools', {'groups': ['work' if len(calls) % 2 else 'reports']}
        elif len(calls) == 1:
            name, args = 'load_tools', {'groups': ['research']}
        else:
            name, args = 'web_fetch', {'url': 'https://example.org/static'}
        requested.append(name)
        return response(calls=[(f'repeat-{len(calls)}', name, args)])
    provider(monkeypatch, chat)
    result, stored = await run(setup, '请查找相关公开资料；没有新增信息就停止。')
    async with setup[1]() as db:
        writes = await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == setup[2]['employee'].id))
    evidence('loop-' + loop, {'modelCalls': len(calls), 'toolRequests': len(requested), 'tools': requested,
        'budget': stored['taskBudget'], 'networkFetches': len(network), 'writes': writes, 'reply': result['reply'],
        'outcome': result['job']['taskOutcome']['state']})
    assert stored['taskBudget']['endedAt'] and len(calls) <= 96 and writes == 0
    assert result['job']['taskOutcome']['state'] == 'blocked'
    assert all(node['state'] not in ('running', 'waiting', 'retry_wait') for node in result['job']['nodes'])
    if loop == 'same_url':
        assert len(network) == 1


class CurrentMislabelledReadModel(MislabelledReadModel):
    """Same repair sequence, without the obsolete entire PUBLIC_REPLY_POLICY literal."""
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            result = completion(self.answer)
            result.tool_calls[0]['args']['business_requested'] = True
        elif self.calls == 2:
            instruction = messages[-1]
            assert instruction.id.startswith('completion-repair:')
            assert '原用户请求还有遗漏的操作' not in instruction.content
            assert '无业务回执是正常的' in instruction.content
            assert '不汇报本次内部纠错' in instruction.content
            self.repairs.append(instruction.content)
            result = AIMessage(content='', tool_calls=[{'name': 'get_business_actions',
                'id': 'inspect-existing-receipts', 'args': {}}])
        else:
            assert self.calls == 3 and isinstance(messages[-1], ToolMessage)
            assert messages[-1].name == 'get_business_actions' and json.loads(messages[-1].content) == []
            result = completion(self.answer)
        return ChatResult(generations=[ChatGeneration(message=result)])


async def test_current_false_business_flag_preserves_no_write_and_hides_internal_repair(setup):
    answer = '注意范围、来源和时效。\n\n[参考文档](https://example.org/guide)'
    fake = CurrentMislabelledReadModel(model='controlled', api_key='unused', answer=answer)
    result, stored = await run_model(setup, fake, '整理三条注意事项，不要保存报告。')
    work = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    evidence('completion-repair-current', {'reply': result['reply'], 'outcome': result['job']['taskOutcome'],
        'actions': result['actions'], 'interactions': result['interactions'], 'repairs': stored.get('deliveryRepairs'),
        'modelCalls': fake.calls, 'repairPrompts': fake.repairs, 'workCount': len(work)})
    assert result['reply'] == answer and result['job']['taskOutcome']['state'] == 'completed'
    assert not result['actions'] and not result['interactions'] and not work
    assert stored['deliveryRepairs'] == ['action'] and len(fake.repairs) == 1
    assert not stored['incompleteTask'] and fake.calls == 3


async def test_document_directory_and_chunk_pages_cover_exact_authorized_sets(setup):
    from app.agent.tools.resources.documents import find_documents, read_document
    from app.modules.attachments.models import Attachment, DocumentChunk
    from app.modules.messages.models import Message
    context, sent = await runtime(setup, '分页读取我发过的资料')
    expected, target = [], None
    async with context.sessions.begin() as db:
        for group in range(3):
            message = Message(company_id=context.company_id, owner_id=context.owner_id,
                conversation_id=sent['conversationId'], text='之前发的文件')
            db.add(message)
            await db.flush()
            for index in range(8 if group < 2 else 7):
                item = Attachment(company_id=context.company_id, owner_id=context.owner_id,
                    message_id=message.id, kind='document', mime='text/plain', name=f'附件{group}-{index}.txt',
                    size=10, sha256='0' * 64, extraction_status='ready', extraction_revision=1)
                db.add(item)
                await db.flush()
                expected.append(item.id)
                if target is None:
                    target = item.id
                    for ordinal in range(10):
                        db.add(DocumentChunk(company_id=context.company_id, owner_id=context.owner_id,
                            attachment_id=item.id, revision=1, ordinal=ordinal,
                            location=f'第{ordinal}段', text=f'共同词 段落_{ordinal:02d}'))
        foreign = Attachment(company_id=context.company_id, owner_id=setup[2]['peer'].id,
            message_id=sent['messageId'], kind='document', mime='text/plain', name='外部机密.txt',
            size=10, sha256='1' * 64, extraction_status='ready', extraction_revision=1)
        db.add(foreign)
    offset, found, pages = 0, [], []
    while True:
        result = json.loads(await find_documents.coroutine('', SimpleNamespace(context=context), start=offset))
        assert len(result['items']) <= 10
        found.extend(row['id'] for row in result['items'])
        pages.append({'cursor': offset, 'count': len(result['items']), 'next': result['nextCursor']})
        if result['nextCursor'] is None:
            break
        assert result['nextCursor'] > offset
        offset = result['nextCursor']
    assert len(found) == len(set(found)) == 23 and set(found) == set(expected)
    evidence_rows = {}
    for name in ('find_documents', 'read_document'):
        offset, chunks, read_pages = 0, [], []
        while True:
            raw = (await find_documents.coroutine('共同词', SimpleNamespace(context=context), attachment_id=target, start=offset)
                if name == 'find_documents' else await read_document.coroutine(target, offset, SimpleNamespace(context=context)))
            page = json.loads(raw)
            assert len(page['items']) <= (3 if name == 'find_documents' else 40)
            assert sum(len(row['text']) for row in page['items']) <= 12_000
            assert all(row['location'] == f"第{row['ordinal']}段"
                       and row['text'] == f"共同词 段落_{row['ordinal']:02d}" for row in page['items'])
            read_pages.append(page)
            assert all(row['citation'] == f"[[file:{target}:1:{row['ordinal']}]]" for row in page['items'])
            chunks.extend(row['ordinal'] for row in page['items'])
            if page['nextCursor'] is None:
                break
            assert page['nextCursor'] == page['items'][-1]['ordinal'] + 1 > offset
            offset = page['nextCursor']
        assert chunks == list(range(10))
        assert len(read_pages) == (4 if name == 'find_documents' else 1)
        evidence_rows[name] = chunks
    evidence('document-tool-pages', {'directoryPages': pages, 'ownDocuments': len(found),
        'foreignExcluded': 1, 'chunkOrdinals': evidence_rows})


async def test_current_message_receipt_set_at_tool_capacity_excludes_foreign_and_other_turns(setup):
    from app.agent.tools.business.actions import get_business_actions
    from app.db.base import uid
    from app.modules.operations.models import BusinessAction
    context, sent = await runtime(setup, '读取本条消息已保存的操作结果')
    expected = []
    async with context.sessions.begin() as db:
        for index in range(64):
            row = BusinessAction(company_id=context.company_id, owner_id=context.owner_id,
                message_id=sent['messageId'], conversation_id=sent['conversationId'], step=index + 1,
                action='delete_work', digest=f'{index:064x}', intent_key=f'{index:064x}',
                access={'role': 'employee'}, state='succeeded')
            db.add(row)
            await db.flush()
            expected.append(row.id)
        for owner, message_id, step in ((setup[2]['peer'].id, sent['messageId'], 65),
                                         (context.owner_id, uid(), 1)):
            db.add(BusinessAction(company_id=context.company_id, owner_id=owner,
                message_id=message_id, conversation_id=sent['conversationId'], step=step,
                action='delete_work', digest='f' * 64, intent_key='f' * 64,
                access={'role': 'employee'}, state='succeeded', result={'message': 'PRIVATE_OTHER_RECEIPT'}))
    raw = await get_business_actions.coroutine(SimpleNamespace(context=context))
    rows = json.loads(raw)
    assert len(rows) == 64 and [row['id'] for row in rows] == expected
    assert all(row['messageId'] == sent['messageId'] and row['state'] == 'succeeded' for row in rows)
    assert 'PRIVATE_OTHER_RECEIPT' not in raw
    evidence('current-message-receipt-set', {'count': len(rows), 'encodedBytes': len(raw.encode()),
        'foreignExcluded': 1, 'otherTurnExcluded': 1, 'orderedIds': expected,
        'scope': 'Seeded receipts at normal per-turn tool capacity; no claim of an independent response byte cap.'})
