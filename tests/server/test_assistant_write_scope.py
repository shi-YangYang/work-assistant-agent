import json
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from app.agent.tools.work import propose_progress
from app.agent.tools.team import propose_followup
from app.modules.work.models import ProgressDraft, WorkItem, WorkRevision
from app.modules.messages.models import Message
from app.modules.operations.mutations.publication import shared_attachment
from app.agent.actions.operations import execute
from test_business_actions import runtime, finish
from test_company import keyed

pytestmark = pytest.mark.asyncio


class ScopeJudge:
    def __init__(self, requested, preview=False): self.requested, self.preview = requested, preview
    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        return AIMessage(content=json.dumps({'allowed': self.requested, 'requireConfirmation': self.preview, 'quote': payload['currentUserText'], 'reason': '仅讨论，不保存' if not self.requested else '', 'notRequested': not self.requested}))


@pytest.mark.parametrize('who,tool', [('employee', propose_progress), ('admin', propose_followup)])
async def test_advice_does_not_silently_save_suggestions(setup, who, tool):
    _, sessions, users, _ = setup
    context, _ = await runtime(setup, '今天做完初稿，帮我分析下步安排，不记录进展', who)
    context.intent_model = ScopeJudge(False)
    args = {'title': '初稿', 'summary': '已完成初稿', 'status': 'in_progress', 'blocker': '', 'next_step': '讨论安排', 'runtime': SimpleNamespace(context=context)}
    if who == 'admin': args['source_tokens'] = []
    result = json.loads(await tool.coroutine(**args))
    assert result['state'] == 'not_requested'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ProgressDraft).where(ProgressDraft.owner_id == users[who].id)) == 0
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users[who].id)) == 0


async def test_explicit_progress_confirmation_publishes_selected_content_only(setup):
    _, sessions, users, c = setup
    context, sent = await runtime(setup, '私人讨论不想公开。请把完成初稿记录为待确认进展')
    context.intent_model = ScopeJudge(True, preview=True)
    result = json.loads(await propose_progress.coroutine('初稿', '完成初稿', 'in_progress', '', '评审', SimpleNamespace(context=context)))
    assert result['status'] == 'pending'
    response = await c['employee'].post('/api/v1/progress-drafts/confirm', json={'items': [{'id': result['draftId'], 'expectedRevision': 1}]}, headers=keyed())
    assert response.status_code == 200
    work = (await c['admin'].get('/api/v1/work-items/' + response.json()['workIds'][0])).json()
    assert work['summary'] == '完成初稿' and work['history'][0]['sourceIds'] == []
    assert (await c['admin'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404
    assert (await c['admin'].get('/api/v1/team/members/' + users['employee'].id + '/messages')).json()['items'] == []
    async with sessions() as db:
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))
        assert revision.publication['originMessageIds'] == [sent['messageId']]


async def test_only_explicitly_attached_material_is_public_and_legacy_sources_remain(setup):
    _, sessions, users, c = setup
    context, sent = await runtime(setup, '帮我创建工作需求核对，并附上公开材料')
    files = []
    for name in ('公开.txt', '私人.txt'):
        upload = await c['employee'].post('/api/v1/uploads', files={'file': (name, name.encode(), 'text/plain')})
        assert upload.status_code == 201, upload.text
        files.append(upload.json())
    from app.modules.attachments.models import Attachment
    async with sessions.begin() as db:
        for item in files:
            (await db.get(Attachment, item['id'])).message_id = sent['messageId']
    result = await execute(context, step=1, action='create_work', changes={'title': '需求核对'}, shared_attachment_ids=[files[0]['id']])
    assert result['state'] == 'succeeded', result
    assert (await c['admin'].get(files[0]['url'])).status_code == 200
    assert (await c['admin'].get(files[1]['url'])).status_code == 404
    assert (await c['admin'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404
    await finish(context)
    context, legacy = await runtime(setup, '历史上报')
    async with sessions.begin() as db:
        (await db.get(Message, legacy['messageId'])).private_context = False
    assert (await c['admin'].get('/api/v1/messages/' + legacy['messageId'])).status_code == 200


async def test_selected_material_survives_private_conversation_deletion(setup):
    from app.agent.tools.team import query_team_business, read_team_source
    from app.agent.tools.documents import read_document
    from app.modules.attachments.models import Attachment, DocumentChunk
    from app.tasks.processing.documents import prepare_document
    _, sessions, users, c = setup
    context, sent = await runtime(setup, '创建需求核对工作，仅附带公开材料')
    files = []
    for name in ('公开.txt', '私密.txt'):
        uploaded = await c['employee'].post('/api/v1/uploads', files={'file': (name, name.encode(), 'text/plain')})
        assert uploaded.status_code == 201
        files.append(uploaded.json())
    async with sessions.begin() as db:
        for item in files:
            (await db.get(Attachment, item['id'])).message_id = sent['messageId']
    await prepare_document(context, files[0]['id'])
    created = await execute(context, step=1, action='create_work', changes={'title': '需求核对'}, shared_attachment_ids=[files[0]['id']])
    assert created['state'] == 'succeeded'
    await finish(context)
    admin, _ = await runtime(setup, '查看员工确认的工作材料', 'admin')
    listing = json.loads(await query_team_business.coroutine(runtime=SimpleNamespace(context=admin)))
    token = listing['items'][0]['token']
    source = json.loads(await read_team_source.coroutine(token=token, runtime=SimpleNamespace(context=admin)))
    assert source['sourceMessageIds'] == []
    assert [item['id'] for item in source['attachments']] == [files[0]['id']]
    document = json.loads(await read_team_source.coroutine(token=token, child_id=files[0]['id'], runtime=SimpleNamespace(context=admin)))
    assert document['content']['text'] == '公开.txt'
    rejected = json.loads(await read_team_source.coroutine(token=token, child_id=files[1]['id'], runtime=SimpleNamespace(context=admin)))
    assert rejected['error']['code'] == 'not_found'
    conversation = (await c['employee'].get('/api/v1/conversations/' + sent['conversationId'])).json()
    deleted = await c['employee'].request('DELETE', '/api/v1/conversations/' + sent['conversationId'], json={'expectedRevision': conversation['revision']})
    assert deleted.status_code == 200
    for who in ('employee', 'admin'):
        assert (await c[who].get(files[0]['url'])).status_code == 200
        assert (await c[who].get(files[1]['url'])).status_code == 404
        assert (await c[who].get('/api/v1/messages/' + sent['messageId'])).status_code == 404
    async with sessions() as db:
        assert (await db.get(Message, sent['messageId'])).text == ''
        assert await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id == files[0]['id']))
    context, _ = await runtime(setup, '查看已保存工作附带的材料')
    result = json.loads(await read_document.coroutine(attachment_id=files[0]['id'], start=0, runtime=SimpleNamespace(context=context)))
    assert result['items'][0]['text'] == '公开.txt'
