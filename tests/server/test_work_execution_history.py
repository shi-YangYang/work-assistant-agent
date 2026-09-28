"""Legacy work tools honor execution policy and revisions retain their actual origin."""
import json
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from app.agent.tools.work import propose_progress, find_work_items
from app.agent.tools.team import propose_followup, query_team_business
from app.agent.operations import execute
from app.modules.work.models import WorkItem, WorkRevision, ProgressDraft
from app.modules.messages.models import Message
from app.tasks.context import RunContext
from test_execution_permissions import mode_runtime
from test_business_actions import create, read_work
from test_business_assistant import facts
from test_company import keyed

pytestmark = pytest.mark.asyncio


class WorkJudge:
    def __init__(self, *, preview=False, append=False, allowed=True):
        self.preview, self.append, self.allowed = preview, append, allowed
        self.inputs = []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        return AIMessage(content=json.dumps({'allowed': self.allowed, 'quote': payload['currentUserText'],
            'reason': '', 'notRequested': not self.allowed, 'requireConfirmation': self.preview,
            'appendFields': ['summary'] if self.append else [],
            'appendValues': {'summary': '今天完成多次提交'} if self.append else {}}))


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
@pytest.mark.parametrize('preview', [False, True])
async def test_progress_modes_preserve_append_date_and_replay_once(setup, mode, preview):
    settings, sessions, users, clients = setup
    work = await create(clients['admin'], '上线web', summary='已有说明', dueDate='2026-10-01')
    context, sent = await mode_runtime(setup, mode, '给上线web补充今天完成多次提交' + ('，先让我确认' if preview else ''), 'admin')
    judge = WorkJudge(preview=preview, append=True)
    context.intent_model = judge
    await read_work(context, work['id'])
    arguments = ('上线web', '今天完成多次提交', 'in_progress', '', '', SimpleNamespace(context=context), work['id'])
    result = json.loads(await propose_progress.coroutine(*arguments))
    pending = mode == 'ask' or preview
    assert result['state'] == ('pending' if pending else 'succeeded'), result
    assert judge.inputs[0]['proposedOperation']['targetContent']['summary'] == '已有说明'
    detail = (await clients['admin'].get('/api/v1/work-items/' + work['id'])).json()
    assert detail['revision'] == (1 if pending else 2)
    if pending:
        response = await clients['admin'].post('/api/v1/progress-drafts/confirm', json={'items': [{'id': result['draftId'], 'expectedRevision': 1}]}, headers=keyed())
        assert response.status_code == 200, response.text
    # A fresh runtime simulates a lost tool response/restarted worker; no model
    # reauthorization or repeated append is permitted after its committed write.
    resumed = RunContext(context.owner_id, context.company_id, context.job_id, context.fence, sessions, settings, source_revision=0, intent_model=judge)
    replay = json.loads(await propose_progress.coroutine(*arguments[:5], SimpleNamespace(context=resumed), work['id']))
    assert replay['draftId'] == result['draftId'] and replay['state'] == 'succeeded'
    assert len(judge.inputs) == 1
    detail = (await clients['admin'].get('/api/v1/work-items/' + work['id'])).json()
    assert detail['summary'] == '已有说明\n今天完成多次提交'
    assert detail['dueDate'] == '2026-10-01' and detail['revision'] == 2
    assert detail['history'][0]['origin'] == ('assistant_confirmed' if pending else 'assistant')
    assert detail['history'][0]['sourceIds'] == []
    assert 'originMessageIds' not in str(detail)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ProgressDraft).where(ProgressDraft.message_id == sent['messageId'])) == 1


async def test_full_does_not_authorize_advice_or_another_owners_work(setup):
    _, sessions, users, clients = setup
    work = await create(clients['peer'], '同事事项')
    context, _ = await mode_runtime(setup, 'full', '聊一下工作，不要保存')
    context.intent_model = WorkJudge(allowed=False)
    args = ('计划', '还在讨论', 'in_progress', '', '', SimpleNamespace(context=context))
    assert json.loads(await propose_progress.coroutine(*args))['state'] == 'not_requested'
    result = json.loads(await propose_progress.coroutine(*args, work['id']))
    assert result['state'] == 'invalid_reference'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 0


async def test_followup_full_saves_own_work_with_verified_team_source(setup):
    _, sessions, users, clients = setup
    await facts(sessions, users['employee'])
    context, _ = await mode_runtime(setup, 'full', '给我创建一项跟进员工报价的督办工作', 'admin')
    context.intent_model = WorkJudge()
    runtime = SimpleNamespace(context=context)
    await find_work_items.coroutine('', runtime)
    listing = json.loads(await query_team_business.coroutine(runtime))
    result = json.loads(await propose_followup.coroutine('跟进报价', '核对报价', 'in_progress', '', '询问进度', [listing['items'][0]['token']], runtime))
    assert result['state'] == 'succeeded', result
    async with sessions() as db:
        draft = await db.get(ProgressDraft, result['draftId'])
        work = await db.get(WorkItem, draft.work_id)
        assert work.owner_id == users['admin'].id and work.business_links


async def test_manual_and_approved_action_history_keep_field_values_and_privacy(setup):
    _, _, _, clients = setup
    work = await create(clients['employee'], '上线web', summary='今天完成多次提交')
    context, sent = await mode_runtime(setup, 'ask', '补充截止日期为2026-10-01')
    await read_work(context, work['id'])
    action = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'dueDate': '2026-10-01'})
    result = await clients['employee'].post('/api/v1/business-actions/' + action['id'] + '/confirm', json={'expectedRevision': action['revision']})
    assert result.status_code == 200, result.text
    patch = await clients['employee'].post('/api/v1/work-items/' + work['id'] + '/progress', json={'title': '上线web', 'status': 'done', 'expectedRevision': 2})
    assert patch.status_code == 200
    detail = (await clients['admin'].get('/api/v1/work-items/' + work['id'])).json()
    assert [row['origin'] for row in detail['history']] == ['manual', 'assistant_confirmed', 'manual']
    assert [row['content']['status'] for row in detail['history']] == ['done', 'in_progress', 'in_progress']
    assert detail['history'][1]['content']['dueDate'] == '2026-10-01'
    assert detail['history'][1]['sourceIds'] == []
    assert (await clients['admin'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404


async def test_origin_migration_backfills_legacy_private_and_manual_revisions(setup):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    _, sessions, users, clients = setup
    work = await create(clients['employee'], '历史工作')
    context, sent = await mode_runtime(setup, 'ask', '准备建议')
    context.intent_model = WorkJudge(preview=True)
    await read_work(context, work['id'])
    draft = json.loads(await propose_progress.coroutine('历史工作', '历史补充', 'in_progress', '', '', SimpleNamespace(context=context), work['id']))
    await clients['employee'].post('/api/v1/progress-drafts/confirm', json={'items': [{'id': draft['draftId'], 'expectedRevision': 1}]}, headers=keyed())
    migration = import_module('app.migrations.versions.0020_work_revision_origin')
    async with sessions.begin() as db:
        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync.connection())):
                migration.downgrade()
                migration.upgrade()
        await db.run_sync(cycle)
        history = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == work['id']).order_by(WorkRevision.revision))).all()
        assert [row.origin for row in history] == ['manual', 'assistant_confirmed']
        assert history[1].source_ids == []
        assert history[1].publication['originMessageIds'] == [sent['messageId']]
