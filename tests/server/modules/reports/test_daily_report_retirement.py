import importlib
import json
from datetime import timedelta
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from app.db.base import now
from app.db.idempotency import Idempotency
from app.modules.members.models import Company
from app.modules.messages.models import Message
from app.modules.conversations.models import Conversation, ConversationContext, ConversationTaskState
from app.modules.conversations.task.task_schemas import TaskInterpretation
from app.modules.interactions.models import AssistantInteraction
from app.modules.operations.models import BusinessAction
from app.modules.operations.receipts import action_dto
from app.modules.reports.models import Report, ReportRevision, ReportObligation, ReportSchedule, ReportNotification
from app.modules.reports.periods import period
from app.modules.reports.schemas import GenerateReport, Rules
from app.modules.work.models import WorkItem, WorkRevision
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from app.tasks.context import RunContext, LostLease
from app.modules.reports.generation.results import save_candidate
from _support.http.company import keyed

pytestmark = pytest.mark.asyncio


async def test_daily_contract_is_rejected_not_coerced(setup):
    _, _, _, clients = setup
    client = clients['employee']
    assert GenerateReport.model_validate({'date': '2026-10-24'}).kind == 'weekly'
    assert GenerateReport.model_json_schema()['properties']['kind']['const'] == 'weekly'
    assert 'daily' not in Rules.model_fields
    assert (await client.post('/api/v1/reports/generate', json={'kind': 'daily', 'date': '2026-10-24'}, headers=keyed())).status_code == 422
    assert (await client.get('/api/v1/reports?kind=daily')).status_code == 410
    assert (await client.get('/api/v1/report-obligations?kind=daily')).status_code == 422
    assert 'daily' not in (await client.get('/api/v1/settings/report-rules')).json()


async def legacy_rows(db, actor):
    for name in ('company_report', 'company_report_schedule', 'company_report_obligation'):
        await db.execute(text(f'ALTER TABLE {name} DROP CONSTRAINT ck_{name}_weekly'))
    conversation = Conversation(company_id=actor.company_id, owner_id=actor.id)
    db.add(conversation); await db.flush()
    message = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, text='原始消息 日报', reply='完整聊天不能删除')
    work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title='原始工作', content={'title': '原始工作', 'summary': '原始进展'})
    db.add_all([message, work]); await db.flush()
    source = WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=1, content=work.content, source_ids=[message.id])
    db.add(source); await db.flush()
    reports = [Report(company_id=actor.company_id, owner_id=actor.id, kind=kind, period='2026-10-19', period_end='2026-10-25', timezone='UTC', content={'completed': kind+'正文'}, candidate={'content': {'completed': kind+'候选'}}, source_ids=[source.id], published_revision=1, deleted=deleted) for kind, deleted in [('daily', False), ('daily', True), ('weekly', False)]]
    db.add_all(reports); await db.flush()
    for report in reports:
        db.add(ReportRevision(company_id=actor.company_id, owner_id=actor.id, report_id=report.id, revision=1, content=report.content, source_ids=report.source_ids))
    daily = reports[0]
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=daily.id, state='running', lease_until=now()+timedelta(minutes=5), fence=3, result={'reportSaved': True, 'content': daily.content})
    db.add(job); await db.flush()
    action = BusinessAction(company_id=actor.company_id, owner_id=actor.id, message_id=message.id, conversation_id=conversation.id, step=1, action='generate_report', digest='a', intent_key='b', state='succeeded', params={}, result={'objectType': 'report', 'objectId': daily.id, 'jobId': job.id, 'reportSnapshot': {'content': daily.content}}, access={'role': 'employee'})
    db.add(action); await db.flush()
    chat = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=message.id, state='succeeded', result={'toolOutcomes': [{'receiptId': action.id, 'reportSnapshot': {'content': daily.content}}], 'unrelated': {'keep': True, 'action':'create_work', 'kind':'daily'}})
    db.add(chat)
    query_message = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, text='查日报', reply='用户保留的聊天')
    db.add(query_message); await db.flush()
    query_job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=query_message.id, state='succeeded', result={'nodeExecution': {'readVersions': {daily.id: 1}, 'nodes': [{'output': json.dumps({'items':[{'id':daily.id,'content':daily.content}]})}]}, 'replySources': {'reads': {daily.id:1}}})
    db.add(query_job); await db.flush()
    for identifier in (job.id, query_job.id, 'unrelated'):
        await db.execute(text("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata) VALUES (:thread, '', '1', 'json', '{}', '{}')"), {'thread':f'{actor.company_id}:{actor.id}:job:{identifier}'})
    db.add(ConversationContext(conversation_id=conversation.id, company_id=actor.company_id, owner_id=actor.id, payload={'cards': [{'objectId':daily.id, 'reportSnapshot':daily.content}]}))
    obligation = ReportObligation(company_id=actor.company_id, owner_id=actor.id, kind='daily', period=daily.period, period_end=daily.period_end, timezone='UTC', rule_revision=1, generate_at=now(), deadline_at=now(), reminders=True, before_minutes=30, report_id=daily.id)
    db.add(obligation); await db.flush()
    db.add(ReportNotification(company_id=actor.company_id, owner_id=actor.id, obligation_id=obligation.id, stage='overdue'))
    db.add(ReportSchedule(company_id=actor.company_id, kind='daily', revision=1, timezone='UTC', rule={'enabled':True}, effective_period=daily.period, next_period=daily.period))
    db.add(Idempotency(company_id=actor.company_id, owner_id=actor.id, action='submit:'+daily.id, key='old', digest='x', response={'ok':True}))
    company = await db.get(Company, actor.company_id)
    company.rules = {**company.rules, 'daily': {'enabled':True}}
    await db.flush()
    return reports, message, work, source, job, action, chat, obligation, conversation


async def test_migration_purges_structured_daily_data_preserves_sources_and_fences(setup):
    settings, sessions, users, clients = setup
    actor = users['employee']
    async with sessions.begin() as db:
        reports, message, work, source, job, action, chat, obligation, conversation = await legacy_rows(db, actor)
        admin = users['admin']
        original_chat = Message(company_id=admin.company_id, owner_id=admin.id, text='原始管理员提问', reply='完整历史回答', access={'actorId':admin.id,'companyId':admin.company_id,'role':'admin','team':True,'reads':{'source':{'type':'report','id':reports[0].id,'ownerId':actor.id,'version':1}}})
        db.add(original_chat); await db.flush()
        old_context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings)
        migration = importlib.import_module('app.migrations.versions.0034_remove_daily_reports')
        def migrate(session):
            original = migration.op
            migration.op = Operations(MigrationContext.configure(session.connection()))
            try: migration.upgrade()
            finally: migration.op = original
        await db.run_sync(migrate)
    async with sessions.begin() as db:
        assert set(await db.scalars(select(Report.id).where(Report.owner_id==actor.id))) == {reports[2].id}
        assert (await db.get(Report, reports[2].id)).content == {'completed':'weekly正文'}
        assert not list(await db.scalars(select(ReportRevision).where(ReportRevision.report_id.in_([r.id for r in reports[:2]]))))
        assert (await db.get(Message,message.id)).text == '原始消息 日报'
        assert (await db.get(Message,message.id)).reply == '完整聊天不能删除'
        assert (await db.get(WorkItem,work.id)).content == work.content
        assert (await db.get(WorkRevision,source.id)).source_ids == [message.id]
        assert await db.get(ReportObligation,obligation.id) is None
        assert 'daily' not in (await db.get(Company, actor.company_id)).rules
        stopped = await db.get(Job,job.id)
        assert stopped.state == 'cancelled' and stopped.fence > old_context.fence and stopped.result == {}
        assert (await db.get(Job,chat.id)).result['unrelated'] == {'keep':True, 'action':'create_work', 'kind':'daily'}
        query_jobs = list(await db.scalars(select(Job).where(Job.owner_id==actor.id, Job.kind=='message', Job.id!=chat.id)))
        assert len(query_jobs)==1
        assert 'daily正文' not in str(query_jobs[0].result)
        assert reports[0].id not in str(query_jobs[0].result)
        receipt = await db.get(BusinessAction,action.id)
        assert receipt.params == {} and receipt.result['reportRetired'] and 'reportSnapshot' not in receipt.result
        assert (await action_dto(db,actor,receipt))['state'] == 'unavailable'
        assert (await db.get(ConversationContext,conversation.id)).payload == {}
        threads = list(await db.scalars(text('SELECT thread_id FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix':actor.company_id+':%'}))
        assert threads == [f'{actor.company_id}:{actor.id}:job:unrelated']
        assert not await db.scalar(select(Idempotency.id).where(Idempotency.owner_id==actor.id))
        with pytest.raises(LostLease): await save_candidate(db,old_context,{'completed':'迟到正文'})
    visible = (await clients['admin'].get('/api/v1/messages/'+original_chat.id)).json()
    assert visible['text']=='原始管理员提问' and visible['reply']=='完整历史回答'
    assert await claim(sessions,actor.id) is None
    assert (await clients['employee'].post('/api/v1/jobs/'+job.id+'/retry',json={})).status_code==404
    assert (await clients['employee'].get('/api/v1/reports/'+reports[0].id)).status_code==404
    with pytest.raises(RuntimeError,match='备份'): migration.downgrade()


async def test_legacy_entrypoints_fail_closed_before_migration(setup):
    from fastapi import HTTPException
    from app.tasks.maintenance.scheduling import schedule_company
    settings, sessions, users, clients = setup
    actor = users['employee']
    async with sessions.begin() as db:
        reports, message, work, source, job, action, chat, obligation, conversation = await legacy_rows(db, actor)
    try:
        for suffix in ('', '/sources', '/deletion'):
            assert (await clients['employee'].get('/api/v1/reports/'+reports[0].id+suffix)).status_code==410
            assert (await clients['peer'].get('/api/v1/reports/'+reports[0].id+suffix)).status_code==404
            assert (await clients['outsider'].get('/api/v1/reports/'+reports[0].id+suffix)).status_code==404
        assert (await clients['employee'].post('/api/v1/reports/'+reports[0].id+'/submit',json={'expectedRevision':1},headers=keyed())).status_code==410
        assert (await clients['employee'].post('/api/v1/reports/'+reports[0].id+'/candidate',json={'expectedRevision':1})).status_code==410
        assert (await clients['admin'].request('DELETE','/api/v1/reports/'+reports[0].id,json={'expectedRevision':1})).status_code==410
        assert (await clients['employee'].post('/api/v1/report-obligations/'+obligation.id+'/prepare',json={},headers=keyed())).status_code==410
        assert (await clients['employee'].get('/api/v1/notifications')).json()['unread']==0
        assert len((await clients['employee'].get('/api/v1/reports')).json()['items'])==1
        async with sessions.begin() as db:
            assert (await action_dto(db,actor,await db.get(BusinessAction,action.id)))['state']=='unavailable'
            with pytest.raises(HTTPException) as stopped:
                await save_candidate(db,RunContext(actor.id,actor.company_id,job.id,job.fence,sessions,settings),{'completed':'迟到正文'})
            assert stopped.value.status_code==410
        await schedule_company(sessions,actor.company_id,now(),50)
        async with sessions.begin() as db:
            live = await db.get(Job,job.id)
            live.lease_until = now()-timedelta(seconds=1)
        assert await claim(sessions,actor.id) is None
        assert (await clients['employee'].post('/api/v1/jobs/'+job.id+'/retry',json={})).status_code==410
    finally:
        async with sessions.begin() as db:
            migration = importlib.import_module('app.migrations.versions.0034_remove_daily_reports')
            def migrate(session):
                original=migration.op
                migration.op=Operations(MigrationContext.configure(session.connection()))
                try: migration.upgrade()
                finally: migration.op=original
            await db.run_sync(migrate)


@pytest.mark.parametrize('phase', ['awaiting_confirmation', 'awaiting_answer'])
async def test_migration_finishes_daily_human_wait_without_retiring_other_waits(setup, phase):
    settings, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    async with sessions.begin() as db:
        reports, message, work, source, child, action, chat, obligation, conversation = await legacy_rows(db, actor)
        action.state, action.params, action.task_id = 'pending', {'kind': 'daily', 'date': '2026-10-19'}, message.id
        chat.state, chat.phase, chat.fence = 'awaiting_input', phase, 7
        chat.lease_until = now() + timedelta(minutes=5)
        interpretation = {'state': 'needs_confirmation' if phase == 'awaiting_confirmation' else 'needs_input',
                          'remaining': ['等待步骤甲'], 'goal': '保留用户目标'}
        node = {'id': 'approval', 'kind': 'tool', 'label': '业务操作', 'scope': 'old', 'attempts': 1,
                'state': 'awaiting_confirmation', 'receiptId': action.id, 'resumable': True,
                'requestKey': 'old-request', 'arguments': {'action': 'generate_report', 'kind': 'daily'}}
        # Include the acceptance probe's compact legacy node as well as the
        # full current DTO shape; neither may retain a resumable daily wait.
        chat.result = {'nodeExecution': {'scope': 'old', 'nodes': [node,
                       {'id': 'legacy', 'scope': 'old', 'state': 'awaiting_confirmation', 'receiptId': action.id}]},
                       'taskInterpretation': interpretation, 'intentTaskInterpretation': interpretation,
                       'explicitTaskContext': interpretation, 'completionWait': {'waitingOperationIds': [action.id]},
                       'taskSnapshot': {'taskId': message.id, 'previousTask': {'id': message.id, 'messageId': message.id,
                                                                            'state': 'needs_confirmation', 'remaining': ['等待步骤甲']}},
                       'toolOutcomes': [{'category': 'confirmation', 'receiptId': action.id}],
                       'taskOutcome': {'state': 'needs_confirmation', 'completed': [], 'remaining': ['等待步骤甲'], 'nextAction': 'confirm'}}
        retired_question = None
        if phase == 'awaiting_answer':
            retired_question = AssistantInteraction(
                company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id,
                message_id=message.id, job_id=chat.id, task_id=message.id, key='retired-question', source_revision=message.transcript_revision,
                questions=[{'id': 'choice', 'prompt': '请选择目标', 'type': 'single', 'allowCustom': False,
                            'options': [{'id': 'old', 'label': '旧对象', 'objectType': 'report', 'objectId': reports[0].id,
                                         'objectRevision': 1}]}])
            db.add(retired_question)
            await db.flush()
            chat.result = {**chat.result, 'waitingInteractionId': retired_question.id}
        task_state = ConversationTaskState(
            company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id,
            payload={'latestMessageId': message.id, 'task': {'id': message.id, 'messageId': message.id,
                     'state': 'needs_confirmation', 'remaining': ['等待步骤甲'], 'question': ['等待步骤甲'],
                     'sources': [{'messageId': message.id, 'quote': message.text}]}})
        db.add(task_state)
        other_conversation = Conversation(company_id=actor.company_id, owner_id=actor.id)
        db.add(other_conversation)
        await db.flush()
        other_message = Message(company_id=actor.company_id, owner_id=actor.id,
                                conversation_id=other_conversation.id, text='请协助原始工作', reply='请补充信息')
        db.add(other_message)
        await db.flush()
        other_job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=other_message.id,
                        state='awaiting_input', phase='awaiting_answer', fence=4)
        db.add(other_job)
        await db.flush()
        other_question = AssistantInteraction(
            company_id=actor.company_id, owner_id=actor.id, conversation_id=other_conversation.id,
            message_id=other_message.id, job_id=other_job.id, task_id=other_message.id, key='other-question', source_revision=other_message.transcript_revision,
            questions=[{'id': 'details', 'prompt': '补充工作细节', 'type': 'text', 'options': [], 'allowCustom': True}])
        db.add(other_question)
        await db.flush()
        other_result = {'waitingInteractionId': other_question.id,
                        'taskInterpretation': {'state': 'needs_input', 'remaining': ['补充工作细节']}}
        other_job.result = other_result
        other_payload = {'latestMessageId': other_message.id,
                         'task': {'id': other_message.id, 'messageId': other_message.id, 'state': 'needs_input',
                                  'remaining': ['补充工作细节']}}
        db.add(ConversationTaskState(company_id=actor.company_id, owner_id=actor.id,
                                    conversation_id=other_conversation.id, payload=other_payload))
        await db.flush()
        old_context = RunContext(actor.id, actor.company_id, chat.id, chat.fence, sessions, settings)
        migration = importlib.import_module('app.migrations.versions.0034_remove_daily_reports')
        def migrate(session):
            original = migration.op
            migration.op = Operations(MigrationContext.configure(session.connection()))
            try:
                migration.upgrade()
            finally:
                migration.op = original
        await db.run_sync(migrate)
    response = await client.get('/api/v1/messages/' + message.id)
    assert response.status_code == 200, response.text
    visible = response.json()
    assert visible['text'] == message.text and visible['reply'] == message.reply
    assert visible['job']['state'] == 'cancelled'
    assert visible['job']['phase'] == 'report_retired'
    assert visible['job']['taskOutcome']['state'] == 'cancelled'
    assert visible['job']['taskOutcome']['nextAction'] == 'none'
    assert visible['job']['nodes'][0]['state'] == 'cancelled'
    assert visible['job']['nodes'][0]['canRetry'] is False
    assert visible['actions'][0]['state'] == 'unavailable'
    if retired_question:
        assert visible['interactions'][0]['state'] in ('cancelled', 'expired')
        assert visible['interactions'][0]['questions'] == []
        rejected = await client.post('/api/v1/interactions/' + retired_question.id + '/answer', headers=keyed(),
                                     json={'expectedRevision': 1, 'answers': [{'questionId': 'choice', 'optionIds': ['old']}]})
        assert rejected.status_code in (409, 422)
    assert (await client.post('/api/v1/jobs/' + chat.id + '/retry', json={})).status_code == 409
    confirmed = await client.post('/api/v1/business-actions/' + action.id + '/confirm', json={'expectedRevision': 1})
    assert confirmed.status_code == 200 and confirmed.json()['state'] == 'unavailable'
    assert not confirmed.json().get('continuation')
    async with sessions.begin() as db:
        live = await db.get(Job, chat.id)
        assert live.state == 'cancelled' and live.fence == old_context.fence + 1 and live.lease_until is None
        for key in ('taskInterpretation', 'intentTaskInterpretation', 'explicitTaskContext'):
            projection = TaskInterpretation.model_validate(live.result[key])
            assert projection.state == 'completed' and projection.remaining == []
        assert 'waitingInteractionId' not in live.result and 'completionWait' not in live.result
        assert live.result['taskSnapshot']['previousTask']['state'] == 'cancelled'
        assert not live.result['taskSnapshot']['previousTask']['remaining']
        task = (await db.get(ConversationTaskState, conversation.id)).payload['task']
        assert task['state'] == 'cancelled' and task['remaining'] == [] and task['question'] == []
        assert task['sources'][0]['quote'] == message.text
        unaffected = await db.get(Job, other_job.id)
        assert (unaffected.state, unaffected.phase, unaffected.fence, unaffected.result) == ('awaiting_input', 'awaiting_answer', 4, other_result)
        assert (await db.get(ConversationTaskState, other_conversation.id)).payload == other_payload
        assert (await db.get(AssistantInteraction, other_question.id)).state == 'waiting'
        assert (await db.get(WorkItem, work.id)).content == work.content
        assert (await db.get(Report, reports[2].id)).content == reports[2].content
        from app.tasks.lease import lease
        with pytest.raises(LostLease):
            await lease(db, old_context)
    answer = await client.post('/api/v1/interactions/' + other_question.id + '/answer', headers=keyed(),
                               json={'expectedRevision': 1, 'answers': [{'questionId': 'details', 'text': '明确工作细节'}]})
    assert answer.status_code == 200, answer.text
    assert answer.json()['interaction']['state'] == 'answered'
    assert answer.json()['continuation']['jobId']


async def test_migration_preserves_unrelated_question_in_same_message(setup):
    _, sessions, users, clients = setup
    actor = users['employee']
    async with sessions.begin() as db:
        _, message, _, _, _, action, chat, _, conversation = await legacy_rows(db, actor)
        action.state, action.params = 'pending', {'kind': 'daily'}
        question = AssistantInteraction(
            company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id,
            message_id=message.id, job_id=chat.id, task_id=message.id, key='independent-question', source_revision=message.transcript_revision,
            questions=[{'id': 'work', 'prompt': '补充另一项工作的细节', 'type': 'text', 'options': [], 'allowCustom': True}])
        db.add(question)
        await db.flush()
        chat.state, chat.phase = 'awaiting_input', 'awaiting_answer'
        chat.result = {'waitingInteractionId': question.id,
                       'taskInterpretation': {'state': 'needs_input', 'remaining': ['补充另一项工作的细节']},
                       'nodeExecution': {'scope': 'old', 'nodes': [
                           {'id': 'daily', 'kind': 'tool', 'label': '业务操作', 'scope': 'old', 'attempts': 1,
                            'state': 'awaiting_confirmation', 'receiptId': action.id},
                           {'id': 'question', 'kind': 'tool', 'label': '补充信息', 'scope': 'old', 'attempts': 1,
                            'state': 'awaiting_input', 'output': {'content': json.dumps({'interactionId': question.id})}}]}}
        await db.flush()
        migration = importlib.import_module('app.migrations.versions.0034_remove_daily_reports')
        def migrate(session):
            original = migration.op
            migration.op = Operations(MigrationContext.configure(session.connection()))
            try:
                migration.upgrade()
            finally:
                migration.op = original
        await db.run_sync(migrate)
    client = clients['employee']
    response = await client.get('/api/v1/messages/' + message.id)
    assert response.status_code == 200, response.text
    visible = response.json()
    assert visible['job']['state'] == 'awaiting_input'
    assert visible['job']['taskOutcome']['nextAction'] == 'reply'
    assert [node['state'] for node in visible['job']['nodes']] == ['cancelled', 'awaiting_input']
    assert visible['interactions'][0]['state'] == 'waiting'
    assert visible['actions'][0]['state'] == 'unavailable'
    answer = await client.post('/api/v1/interactions/' + question.id + '/answer', headers=keyed(),
                               json={'expectedRevision': 1, 'answers': [{'questionId': 'work', 'text': '工作详细内容'}]})
    assert answer.status_code == 200, answer.text
    assert answer.json()['continuation']['jobId']
