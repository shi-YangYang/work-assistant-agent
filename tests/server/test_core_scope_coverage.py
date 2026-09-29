"""Concrete private objects stay intact after foreign, stale and invalid requests."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.actions.interactions import ask, finish_waiting
from app.db.idempotency import Idempotency
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import Conversation
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.interactions.models import AssistantInteraction
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import ProgressDraft, WorkItem, WorkRevision
from app.tasks.models import Job
from test_company import keyed
from test_documents import upload
from test_execution_permissions import mode_runtime
from test_full_system_acceptance import evidence

pytestmark = pytest.mark.asyncio


async def snapshot(sessions, companies):
    models = (Conversation, Message, Job, ProgressDraft, WorkItem, WorkRevision, Report, ReportRevision,
              Attachment, AssistantInteraction, Deliverable, DeliverableRevision, Idempotency)
    async with sessions() as db:
        result = {}
        for model in models:
            rows = (await db.scalars(select(model).where(model.company_id.in_(companies)).order_by(model.id))).all()
            result[model.__name__] = [{column.name: getattr(row, column.name) for column in model.__table__.columns} for row in rows]
        return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)


async def test_foreign_and_invalid_core_requests_preserve_real_objects_and_job_state(setup):
    _, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    private = '仅对象所有者可见的受控正文'
    context, sent = await mode_runtime(setup, 'auto', private)
    asked = await ask(context, [{'id': 'scope', 'prompt': private, 'type': 'text'}])
    assert await finish_waiting(context)
    work = await client.post('/api/v1/work-items', json={'title': private, 'summary': private}, headers=keyed())
    assert work.status_code == 201
    document = await upload(client, 'scope.txt', private.encode())
    async with sessions.begin() as db:
        attachment = await db.get(Attachment, document['id'])
        attachment.message_id, attachment.extraction_status = sent['messageId'], 'ready'
        report = Report(company_id=actor.company_id, owner_id=actor.id, kind='daily', period='2026-09-29',
            period_end='2026-09-29', timezone='UTC', content={'completed': private, 'ongoing': '', 'blockers': '', 'next': ''})
        draft = ProgressDraft(company_id=actor.company_id, owner_id=actor.id, message_id=sent['messageId'],
            content={'title': private, 'summary': private}, tool_key=uuid4().hex)
        deliverable = Deliverable(company_id=actor.company_id, owner_id=actor.id, conversation_id=sent['conversationId'], title=private)
        db.add_all([report, draft, deliverable])
        await db.flush()
        db.add(DeliverableRevision(company_id=actor.company_id, owner_id=actor.id, deliverable_id=deliverable.id,
            revision=1, message_id=sent['messageId'], step=1, title=private, body=private, digest=uuid4().hex))
        report_id, draft_id = report.id, draft.id
    conversation_id = sent['conversationId']
    commands = [
        ('GET', f'/api/v1/conversations/{conversation_id}/deletion', None),
        ('DELETE', f'/api/v1/conversations/{conversation_id}', {'expectedRevision': 1}),
        ('GET', f'/api/v1/conversations/{conversation_id}/interactions', None),
        ('GET', f'/api/v1/deliverables?conversationId={conversation_id}', None),
        ('POST', f"/api/v1/interactions/{asked['interactionId']}/cancel", {'expectedRevision': 1}),
        ('GET', f"/api/v1/jobs/{sent['jobId']}", None),
        ('GET', f'/api/v1/messages?conversationId={conversation_id}', None),
        ('PATCH', f'/api/v1/progress-drafts/{draft_id}', {'title': '不得写入', 'expectedRevision': 1}),
        ('PATCH', f'/api/v1/reports/{report_id}', {'content': {'completed': '不得写入'}, 'expectedRevision': 1}),
        ('GET', f'/api/v1/reports/{report_id}/deletion', None),
        ('POST', f'/api/v1/reports/{report_id}/submit', {'expectedRevision': 1}),
        ('POST', f"/api/v1/uploads/{document['id']}/retry", None),
        ('DELETE', f"/api/v1/work-items/{work.json()['id']}", {'expectedRevision': 1}),
    ]
    companies = [actor.company_id, users['outsider'].company_id]
    before = await snapshot(sessions, companies)
    observed = []
    for role in ('peer', 'outsider'):
        for method, path, body in commands:
            response = await clients[role].request(method, path, json=body, headers=keyed())
            assert response.status_code == 404, (role, method, path, response.text)
            assert private not in response.text
            observed.append({'role': role, 'method': method, 'path': path, 'status': 404})
        # An unfiltered own list may return 200, but must never include this user's work.
        listing = await clients[role].get('/api/v1/work-items')
        assert listing.status_code == 200 and listing.json()['items'] == []
    stale = [
        ('DELETE', f'/api/v1/conversations/{conversation_id}', {'expectedRevision': 99}),
        ('POST', f"/api/v1/interactions/{asked['interactionId']}/cancel", {'expectedRevision': 99}),
        ('PATCH', f'/api/v1/progress-drafts/{draft_id}', {'title': '不得写入', 'expectedRevision': 99}),
        ('PATCH', f'/api/v1/reports/{report_id}', {'content': {'completed': '不得写入'}, 'expectedRevision': 99}),
        ('POST', f'/api/v1/reports/{report_id}/submit', {'expectedRevision': 99}),
        ('POST', f"/api/v1/uploads/{document['id']}/retry", None),
        ('DELETE', f"/api/v1/work-items/{work.json()['id']}", {'expectedRevision': 99}),
    ]
    for method, path, body in stale:
        response = await client.request(method, path, json=body, headers=keyed())
        assert response.status_code == 409, (method, path, response.text)
        observed.append({'role': 'owner-stale-or-ready', 'method': method, 'path': path, 'status': 409})
    invalid = [
        ('GET', f'/api/v1/messages?conversationId={conversation_id}&limit=101', None),
        ('GET', '/api/v1/work-items?limit=21', None),
        ('GET', '/api/v1/notifications?cursor=-1', None),
        ('GET', f'/api/v1/deliverables?conversationId={conversation_id}&offset=-1', None),
        ('PATCH', f'/api/v1/progress-drafts/{draft_id}', {'title': ' ', 'expectedRevision': 1}),
        ('PATCH', f'/api/v1/reports/{report_id}', {'content': {'unknown': '不得写入'}, 'expectedRevision': 1}),
        ('POST', f'/api/v1/reports/{report_id}/submit', {'expectedRevision': 0}),
    ]
    for method, path, body in invalid:
        response = await client.request(method, path, json=body, headers=keyed())
        assert response.status_code == 422, (method, path, response.text)
        observed.append({'role': 'owner-invalid-input', 'method': method, 'path': path, 'status': 422})
    assert await snapshot(sessions, companies) == before
    own = await client.get(f'/api/v1/messages?conversationId={conversation_id}')
    assert own.status_code == 200 and own.json()['items'][0]['text'] == private
    own_deliverable = await client.get(f'/api/v1/deliverables?conversationId={conversation_id}')
    assert own_deliverable.status_code == 200 and own_deliverable.json()['items'][0]['title'] == private
    evidence('core-scope-and-input', {'requests': observed, 'snapshotTables': 13, 'objectsAndJobsUnchanged': True,
                                       'ownObjectsStillReadable': True})


async def test_every_explicit_admin_route_rejects_employee_without_changing_real_resources(setup):
    from inspect import signature
    from app.http.dependencies import ADMIN, READ_ADMIN
    from app.modules.auth.models import DingTalkAuthorization, DingTalkConfig, DingTalkIdentity
    from app.modules.members.models import Company, Member
    from app.modules.model_services.models import ModelCheck, ModelRouting, ModelService, ModelServiceRevision, ModelUsage
    from app.modules.reports.models import ReportSchedule
    from app.modules.support.models import SupportFeedback
    from app.modules.voiceprints.models import Voiceprint, VoiceprintCleanup
    from test_desktop_voiceprints import enroll
    from test_model_services import create, payload, route
    _, sessions, users, clients = setup
    saved = await create(clients['admin'])
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=route(saved))).status_code == 200
    assert (await enroll(clients['admin'], users['employee'].id)).status_code == 202
    support = await clients['employee'].post('/api/v1/support-feedback', json={'description': '角色矩阵的真实反馈'}, headers=keyed())
    assert support.status_code == 201
    async with sessions.begin() as db:
        (await db.get(Member, users['outsider'].id)).role = 'admin'
    models = (Company, Member, ModelCheck, ModelRouting, ModelService, ModelServiceRevision, ModelUsage,
              DingTalkAuthorization, DingTalkConfig, DingTalkIdentity, ReportSchedule, SupportFeedback, Voiceprint, VoiceprintCleanup)

    async def admin_snapshot():
        async with sessions() as db:
            result = {}
            for model in models:
                rows = (await db.execute(select(model.__table__).order_by(*model.__table__.primary_key))).mappings().all()
                result[model.__name__] = [dict(row) for row in rows]
            return json.dumps(result, sort_keys=True, default=str)

    before = await admin_snapshot()
    observed = []
    app = clients['employee']._transport.app
    def registered_routes(router):
        for registered in router.routes:
            nested = getattr(registered, 'original_router', None)
            if nested is not None:
                yield from registered_routes(nested)
            else:
                yield registered

    for registered in registered_routes(app):
        if not hasattr(registered, 'endpoint'):
            continue
        actor = signature(registered.endpoint).parameters.get('actor')
        if not actor or actor.default not in (ADMIN, READ_ADMIN):
            continue
        identifier = saved['id'] if '/model-services/' in registered.path else support.json()['id'] if '/support-feedback/' in registered.path else users['employee'].id
        path = registered.path.replace('{identifier}', identifier).replace('{view}', 'work')
        for method in sorted(registered.methods - {'HEAD', 'OPTIONS'}):
            response = await clients['employee'].request(method, path, json={} if method != 'GET' else None, headers=keyed())
            assert response.status_code == 403, (method, registered.path, response.text)
            assert response.json()['error']['message'] == '仅老板／管理员可进行此操作'
            observed.append({'operation': method + ' ' + registered.path, 'status': 403, 'assertion': 'role-denied-before-business-side-effect'})
    assert observed and await admin_snapshot() == before
    # Valid mutation bodies and real foreign objects distinguish tenant isolation
    # from missing-object or payload-validation failures.
    foreign = [
        ('PATCH', '/api/v1/members/' + users['employee'].id, {'active': False}),
        ('POST', '/api/v1/members/' + users['employee'].id + '/reset-password', {'password': 'controlled-new-password'}),
        ('PATCH', '/api/v1/settings/model-services/' + saved['id'], {**payload(), 'expectedRevision': 1}),
        ('DELETE', '/api/v1/settings/model-services/' + saved['id'], {'expectedRevision': 1}),
        ('DELETE', '/api/v1/settings/voiceprints/' + users['employee'].id, None),
    ]
    for method, path, body in foreign:
        response = await clients['outsider'].request(method, path, json=body, headers=keyed())
        assert response.status_code == 404, (method, path, response.text)
    assert await admin_snapshot() == before
    assert (await clients['admin'].get('/api/v1/settings/model-services/' + saved['id'])).json() == saved
    evidence('explicit-admin-role-boundaries', {'requests': observed, 'foreignRealObjectsRejected': len(foreign),
                                               'snapshotTables': len(models), 'allResourcesUnchanged': True})
