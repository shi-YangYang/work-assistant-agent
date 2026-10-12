"""Real transactions: direct effort configuration, scoped preference and task snapshots."""
import asyncio
import json
from copy import deepcopy
import pytest
from sqlalchemy import select
from app.modules.members.models import Member
from app.modules.model_services.bindings import bind_job, resolve_bound
from app.modules.model_services.schemas import Reasoning, ServiceModel
from app.tasks.models import Job
from _support.http.company import keyed
from _support.http.model_services import create, payload, route

pytestmark = pytest.mark.asyncio
PATH = '/api/v1/assistant/reasoning-settings'


async def configure(clients):
    body = payload()
    body['models'][0]['reasoning'] = {'efforts': ['low', 'high', 'max'], 'initial': 'high'}
    saved = await create(clients['admin'], body)
    routing = route(saved)
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 200
    return saved, routing


def reference(view, effort=None):
    return {'effort': effort or (view['selected'] or {}).get('effort'), 'preferenceRevision': view['preferenceRevision'], 'configVersion': view['configVersion']}


async def choose(client, effort):
    current = (await client.get(PATH)).json()
    result = await client.patch(PATH, json=reference(current, effort))
    assert result.status_code == 200, result.text
    return result.json()


async def test_validation_sanitized_settings_security_and_account_persistence(setup):
    _, sessions, users, clients = setup
    empty = (await clients['employee'].get(PATH)).json()
    assert empty['options'] == [] and empty['selected'] is None
    saved, _ = await configure(clients)
    first = (await clients['employee'].get(PATH)).json()
    assert first['selected'] == {'effort': 'high'}
    assert set(first) == {'options', 'selected', 'preferenceRevision', 'configVersion'}
    assert 'baseUrl' not in json.dumps(first) and 'parameters' not in json.dumps(first) and 'preset' not in json.dumps(first)
    for invalid in ('private', 'foreign-effort'):
        assert (await clients['employee'].patch(PATH, json=reference(first, invalid))).status_code == 422
    assert (await clients['outsider'].patch(PATH, json=reference(first, 'low'))).status_code == 409
    assert (await clients['employee'].patch(PATH, json={**reference(first, 'low'), 'parameters': {'reasoning_effort': 'max'}})).status_code == 422
    assert (await clients['employee'].patch('/api/v1/settings/model-services/' + saved['id'], json=payload())).status_code == 403
    saved_pref = await choose(clients['employee'], 'low')
    assert saved_pref['preferenceRevision'] == 1
    assert (await clients['peer'].get(PATH)).json()['selected']['effort'] == 'high'
    login = await clients['employee'].post('/api/v1/auth/login', json={'username': users['employee'].username, 'password': 'controlled-test-password'})
    clients['employee'].headers['X-CSRF-Token'] = login.json()['csrf']
    assert (await clients['employee'].get(PATH)).json() == saved_pref
    async with sessions() as db:
        member = await db.get(Member, users['employee'].id)
        assert member.reasoning_preference == {'serviceId': saved['id'], 'modelId': 'chat', 'effort': 'low'}


async def test_concurrent_selection_config_invalidation_and_administrator_initial(setup):
    _, _, _, clients = setup
    saved, routing = await configure(clients)
    current = (await clients['employee'].get(PATH)).json()
    responses = await asyncio.gather(*(clients['employee'].patch(PATH, json=reference(current, effort)) for effort in ('low', 'max')))
    assert sorted(r.status_code for r in responses) == [200, 409]
    chosen = (await clients['employee'].get(PATH)).json()
    body = {**payload(), 'models': deepcopy(saved['models']), 'apiKey': '', 'expectedRevision': 1}
    body['models'][0]['reasoning']['initial'] = 'max'
    assert (await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json=body)).status_code == 200
    assert (await clients['employee'].get(PATH)).json()['selected'] == chosen['selected']
    assert (await clients['peer'].get(PATH)).json()['selected']['effort'] == 'max'
    assert (await clients['employee'].patch(PATH, json=reference(chosen, 'high'))).status_code == 409
    await choose(clients['employee'], 'low')
    body['expectedRevision'] = 2
    body['models'][0]['reasoning']['efforts'] = ['high', 'max']
    assert (await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json=body)).status_code == 200
    invalidated = (await clients['employee'].get(PATH)).json()
    assert invalidated['selected']['effort'] == 'max' and invalidated['preferenceRevision'] > chosen['preferenceRevision']
    routing.update(expectedRevision=1)
    routing['assistant']['presetId'] = 'obsolete'
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 422


async def test_first_configuration_needs_only_model_save_and_preserves_accepted_task(setup):
    settings, sessions, _, clients = setup
    saved = await create(clients['admin'])
    routing = route(saved)
    before_routing = (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).json()
    before_view = (await clients['employee'].get(PATH)).json()
    accepted = await clients['employee'].post('/api/v1/messages', json={'text': '设置前接受的消息', 'reasoning': reference(before_view)}, headers=keyed())
    assert accepted.status_code == 202, accepted.text
    body = {**payload(), 'models': deepcopy(saved['models']), 'apiKey': '', 'expectedRevision': 1}
    body['models'][0]['reasoning'] = {'efforts': ['low', 'high'], 'initial': None}
    path = '/api/v1/settings/model-services/' + saved['id']
    assert (await clients['admin'].patch(path, json=body)).status_code == 422
    assert (await clients['admin'].get(path)).json() == saved
    body['models'][0]['reasoning']['initial'] = 'high'
    assert (await clients['admin'].patch(path, json={**body, 'expectedRevision': 0})).status_code == 409
    changed = await clients['admin'].patch(path, json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()['revision'] == 2
    assert (await clients['admin'].get('/api/v1/settings/model-routing')).json() == before_routing
    after_view = (await clients['employee'].get(PATH)).json()
    assert after_view['selected'] == {'effort': 'high'} and after_view['configVersion'] != before_view['configVersion']
    stale = await clients['employee'].post('/api/v1/messages', json={'text': '过期的设置', 'newConversation': True, 'reasoning': reference(before_view)}, headers=keyed())
    assert stale.status_code == 409
    async with sessions() as db:
        job = await db.get(Job, accepted.json()['jobId'])
        assert job.model_binding['assistant']['effort'] is None and job.model_binding['assistant']['revision'] == 1
        config, _ = await resolve_bound(db, settings, job.company_id, job.model_binding, 'assistant')
        assert config['parameters'] == {}


async def test_removed_option_falls_back_only_affected_accounts_and_report_stays_explicit(setup):
    settings, sessions, users, clients = setup
    saved, routing = await configure(clients)
    routing.update(expectedRevision=1, report={**routing['assistant'], 'parameters': {'reasoning_effort': 'medium', 'temperature': .4}, 'explicitReasoning': True})
    before_routing = (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).json()
    invalid = await choose(clients['employee'], 'high')
    valid = await choose(clients['peer'], 'low')
    body = {**payload(), 'models': deepcopy(saved['models']), 'apiKey': '', 'expectedRevision': 1}
    body['models'][0]['reasoning'] = {'efforts': ['low', 'max'], 'initial': 'max'}
    response = await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json=body)
    assert response.status_code == 200, response.text
    assert (await clients['admin'].get('/api/v1/settings/model-routing')).json() == before_routing
    fallback = (await clients['employee'].get(PATH)).json()
    assert fallback['selected']['effort'] == 'max' and fallback['preferenceRevision'] == invalid['preferenceRevision'] + 1
    retained = (await clients['peer'].get(PATH)).json()
    assert retained['selected'] == valid['selected'] and retained['preferenceRevision'] == valid['preferenceRevision']
    from types import SimpleNamespace
    async with sessions() as db:
        job = SimpleNamespace(kind='report', result={}, model_binding=None, config_attempt=0, company_id=users['employee'].company_id)
        binding = await bind_job(db, job, settings)
        config, _ = await resolve_bound(db, settings, job.company_id, binding, 'report')
        assert config['parameters'] == {'reasoning_effort': 'medium', 'temperature': .4}


async def test_invalid_model_change_is_atomic_and_initial_has_one_source(setup):
    _, _, _, clients = setup
    saved, _ = await configure(clients)
    before_routing = (await clients['admin'].get('/api/v1/settings/model-routing')).json()
    explicit = await choose(clients['employee'], 'max')
    body = {**payload(), 'models': deepcopy(saved['models']), 'apiKey': '', 'expectedRevision': 1}
    body['models'][0]['reasoning']['initial'] = 'not-allowed'
    path = '/api/v1/settings/model-services/' + saved['id']
    assert (await clients['admin'].patch(path, json=body)).status_code == 422
    assert (await clients['admin'].get(path)).json() == saved
    body['models'][0]['reasoning']['initial'] = 'low'
    assert (await clients['admin'].patch(path, json=body)).status_code == 200
    assert (await clients['admin'].get('/api/v1/settings/model-routing')).json() == before_routing
    retained = (await clients['employee'].get(PATH)).json()
    assert retained['selected'] == explicit['selected'] and retained['preferenceRevision'] == explicit['preferenceRevision']
    assert (await clients['peer'].get(PATH)).json()['selected']['effort'] == 'low'


async def test_acceptance_snapshot_idempotency_stale_sends_and_manual_retry(setup):
    settings, sessions, users, clients = setup
    saved, _ = await configure(clients)
    view = await choose(clients['employee'], 'low')
    headers = keyed()
    body = {'text': '已接受的消息', 'newConversation': True, 'reasoning': reference(view)}
    sent = await clients['employee'].post('/api/v1/messages', json=body, headers=headers)
    assert sent.status_code == 202, sent.text
    identifiers = sent.json()
    await choose(clients['employee'], 'max')
    # Idempotent replay is resolved before checking current preferences.
    assert (await clients['employee'].post('/api/v1/messages', json=body, headers=headers)).json() == identifiers
    stale = await clients['employee'].post('/api/v1/messages', json=body, headers=keyed())
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'reasoning_settings_changed'
    changed = {**payload(), 'models': deepcopy(saved['models']), 'apiKey': '', 'expectedRevision': 1}
    changed['models'][0]['reasoning']['parameterOverrides'] = {'low': {'reasoning_effort': 'low', 'temperature': .4}}
    assert (await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json=changed)).status_code == 200
    async with sessions.begin() as db:
        job = await db.get(Job, identifiers['jobId'])
        before = deepcopy(job.model_binding)
        assert before['assistant']['effort'] == 'low' and before['assistant']['revision'] == 1
        assert await bind_job(db, job, settings) == before
        config, _ = await resolve_bound(db, settings, job.company_id, before, 'assistant')
        assert config['parameters'] == {'reasoning_effort': 'low'}
        job.state = 'failed'
    retry = await clients['employee'].post('/api/v1/jobs/' + identifiers['jobId'] + '/retry', json={})
    assert retry.status_code == 200, retry.text
    async with sessions() as db:
        job = await db.get(Job, identifiers['jobId'])
        assert job.model_binding['assistant']['effort'] == 'max' and job.model_binding['assistant']['revision'] == 2
        assert job.config_attempt == 1
    # Old requests omit the new field completely and still freeze current account settings.
    legacy_headers = keyed()
    legacy = {'text': '旧客户端', 'newConversation': True}
    old = await clients['employee'].post('/api/v1/messages', json=legacy, headers=legacy_headers)
    assert old.status_code == 202
    assert (await clients['employee'].post('/api/v1/messages', json={**legacy, 'reasoning': None}, headers=legacy_headers)).json() == old.json()


@pytest.mark.parametrize('natural', [False, True])
async def test_question_continuation_uses_original_snapshot(setup, natural):
    from app.agent.actions.interactions import ask, finish_waiting
    from app.agent.context.task_context import select_continuation
    from app.tasks.runtime.queue import claim
    from app.tasks.context import RunContext
    settings, sessions, users, clients = setup
    await configure(clients)
    await choose(clients['employee'], 'low')
    first = (await clients['employee'].post('/api/v1/messages', json={'text': '安排工作，请先确认日期'}, headers=keyed())).json()
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, model_binding=job.model_binding)
    asked = await ask(context, [{'id': 'date', 'prompt': '哪一天', 'type': 'text'}])
    await finish_waiting(context)
    await choose(clients['employee'], 'max')
    if natural:
        result = await clients['employee'].post('/api/v1/messages', json={'text': '下周五', 'conversationId': first['conversationId']}, headers=keyed())
        continuation = result.json()
        job = await claim(sessions, users['employee'].id)
        assert job.model_binding['assistant']['effort'] == 'max'
        context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, model_binding=job.model_binding)
        await select_continuation(context, True)
        assert context.model_binding['assistant']['effort'] == 'low'
    else:
        result = await clients['employee'].post('/api/v1/interactions/' + asked['interactionId'] + '/answer', json={'expectedRevision': 1, 'answers': [{'questionId': 'date', 'text': '下周五'}]}, headers=keyed())
        continuation = result.json()['continuation']
    assert result.status_code in (200, 202), result.text
    async with sessions() as db:
        job = await db.get(Job, continuation['jobId'])
        assert job.model_binding['assistant']['effort'] == 'low'
        assert await bind_job(db, job, settings) == job.model_binding


async def test_direct_effort_validation_and_advanced_protocol_mapping():
    from app.modules.model_services.parameters import request_options
    for options in ({'reasoning_effort': 'low'}, {'enable_thinking': False, 'reasoning_effort': 'high'}, {'thinking': {'type': 'disabled'}, 'reasoning_effort': 'high'}, {'temperature': .1}):
        with pytest.raises(ValueError):
            ServiceModel(id='m', model='m', reasoning={'efforts': ['high'], 'initial': 'high', 'parameterOverrides': {'high': options}})
    assert request_options({'parameters': {}, 'legacyParameters': {'enable_thinking': False}}) == {'enable_thinking': False}
    nested = ServiceModel(id='m', model='m', parameters={'reasoning': {'effort': 'low'}, 'temperature': .2}, reasoning={'efforts': ['low', 'max'], 'initial': 'max'})
    assert request_options(nested.model_dump()) == {'reasoning': {'effort': 'max'}, 'temperature': .2}
    for invalid in ({'efforts': ['high', 'high'], 'initial': 'high'}, {'efforts': ['high'], 'initial': None}, {'efforts': [], 'initial': 'low'}, {'efforts': ['HIGH'], 'initial': 'HIGH'}):
        with pytest.raises(ValueError): Reasoning(**invalid)
    for obsolete in ({'presets': []}, {'selectedPresetId': None}):
        with pytest.raises(ValueError): ServiceModel(id='m', model='m', **obsolete)


async def test_legacy_pending_message_replays_exact_digest_but_unaccepted_reference_requires_sync(setup):
    from app.db.idempotency import idem_begin, idem_save
    from app.modules.messages.schemas import SendMessage
    _, sessions, users, clients = setup
    await configure(clients)
    accepted = (await clients['employee'].post('/api/v1/messages', json={'text': '已接受旧消息'}, headers=keyed())).json()
    legacy = {'text': '旧界面消息', 'reasoning': {'presetId': 'legacy-high', 'preferenceRevision': 3, 'configVersion': 'old-version'}}
    headers = keyed()
    parsed = SendMessage(**legacy)
    # Seed the exact wire digest written by the earlier server version.
    payload = parsed.model_dump()
    for field in ('workReference', 'executionMode', 'fullAccessConfirmed', 'deliverableReference', 'personaId', 'voiceCommandAttachmentId', 'voiceCommandAttachmentIds', 'newConversation'):
        payload.pop(field)
    async with sessions.begin() as db:
        _, digest = await idem_begin(db, users['employee'], 'message', headers['Idempotency-Key'], payload)
        idem_save(db, users['employee'], 'message', headers['Idempotency-Key'], digest, accepted)
    replay = await clients['employee'].post('/api/v1/messages', json=legacy, headers=headers)
    assert replay.status_code == 202 and replay.json() == accepted
    new = await clients['employee'].post('/api/v1/messages', json=legacy, headers=keyed())
    assert new.status_code == 409 and new.json()['error']['code'] == 'reasoning_settings_changed'


async def test_legacy_snapshot_resolves_old_parameters_without_active_presets(setup):
    from app.modules.model_services.models import ModelServiceRevision
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    async with sessions.begin() as db:
        revision = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id == saved['id']))
        revision.models = [{'id': 'chat', 'model': 'controlled-chat', 'protocol': 'chat', 'presets': [{'id': 'old-high', 'mode': 'advanced', 'parameters': {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'temperature': .3}}], 'selectedPresetId': None}]
        binding = {'assistant': {'serviceId': saved['id'], 'revisionId': revision.id, 'modelId': 'chat', 'presetId': 'old-high', 'streaming': True}}
        await db.flush()
        config, _ = await resolve_bound(db, settings, users['employee'].company_id, binding, 'assistant')
        assert config['parameters'] == {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'temperature': .3}
        assert (await clients['admin'].get('/api/v1/settings/model-services/' + saved['id'])).json()['models'][0]['reasoning']['efforts'] == []


async def test_follow_report_preserves_old_explicit_empty_parameter_semantics(setup):
    from types import SimpleNamespace
    from app.modules.model_services.reasoning.legacy import direct_model, migrated_choices
    from app.modules.model_services.parameters import report_model_config
    settings, sessions, users, clients = setup
    old = {'id': 'chat', 'model': 'deepseek-chat', 'protocol': 'chat', 'presets': [{'id': 'empty', 'mode': 'advanced', 'parameters': {}}], 'selectedPresetId': 'empty'}
    body = payload(url='https://api.deepseek.com/v1')
    body['models'][0] = direct_model(old)
    saved = await create(clients['admin'], body)
    routing = route(saved)
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 200
    async with sessions() as db:
        job = SimpleNamespace(kind='report', result={}, model_binding=None, config_attempt=0, company_id=users['employee'].company_id)
        binding = await bind_job(db, job, settings)
        config, _ = await resolve_bound(db, settings, job.company_id, binding, 'report')
        assert config['parameters'] == {} and binding['report']['explicitReasoning'] is True
        assert report_model_config(config, binding['report']) is config
    direct_routing = {**routing, 'report': {**routing['assistant'], 'parameters': {'temperature': .8}, 'explicitReasoning': True}}
    assert migrated_choices(direct_routing, {(saved['id'], 'chat'): body['models'][0]}) == direct_routing


@pytest.mark.parametrize('report_preset,expected_effort,expected_parameters', [
    (None, None, {'thinking': {'type': 'disabled'}}),
    ('empty', None, {}),
    ('medium', 'medium', {'reasoning_effort': 'medium'}),
    ('nested', 'medium', {'reasoning': {'effort': 'medium'}}),
])
async def test_migrated_independent_report_binding_uses_its_actual_parameters(setup, report_preset, expected_effort, expected_parameters):
    from types import SimpleNamespace
    from app.modules.model_services.reasoning.legacy import direct_model, migrated_choices
    from app.modules.model_services.parameters import report_model_config
    settings, sessions, users, clients = setup
    old = {
        'id': 'chat', 'model': 'deepseek-chat', 'protocol': 'chat',
        'presets': [
            {'id': 'high', 'value': 'high', 'assistantEffort': 'high'},
            {'id': 'empty', 'mode': 'advanced', 'parameters': {}},
            {'id': 'medium', 'value': 'medium'},
            {'id': 'nested', 'mode': 'advanced', 'parameters': {'reasoning': {'effort': 'medium'}}},
        ],
        'selectedPresetId': 'high',
    }
    body = payload(url='https://api.deepseek.com/v1')
    body['models'][0] = direct_model(old)
    saved = await create(clients['admin'], body)
    routing = route(saved)
    routing['report'] = {**routing['assistant'], 'presetId': report_preset}
    routing = migrated_choices(routing, {(saved['id'], 'chat'): old})
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 200
    async with sessions() as db:
        job = SimpleNamespace(kind='report', result={}, model_binding=None, config_attempt=0, company_id=users['employee'].company_id)
        binding = await bind_job(db, job, settings)
        config, _ = await resolve_bound(db, settings, job.company_id, binding, 'report')
        assert binding['report']['effort'] == expected_effort
        assert binding['report']['explicitReasoning'] is (report_preset is not None)
        assert report_model_config(config, binding['report'])['parameters'] == expected_parameters
        assistant = SimpleNamespace(kind='message', result={}, model_binding=None, config_attempt=0, company_id=job.company_id, owner_id=users['employee'].id)
        assistant_binding = await bind_job(db, assistant, settings)
        assert assistant_binding['assistant']['effort'] == 'high'
        assert assistant_binding['assistant']['parameters'] == {'reasoning_effort': 'high'}


async def test_nested_direct_effort_is_not_disabled_for_independent_reports(setup):
    from types import SimpleNamespace
    from app.modules.model_services.parameters import report_model_config
    settings, sessions, users, clients = setup
    body = payload(url='https://api.deepseek.com/v1')
    body['models'][0].update(model='deepseek-chat', parameters={'reasoning': {'effort': 'high'}}, reasoning={'efforts': [], 'initial': None})
    saved = await create(clients['admin'], body)
    routing = route(saved)
    routing['report'] = {**routing['assistant']}
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 200
    async with sessions() as db:
        job = SimpleNamespace(kind='report', result={}, model_binding=None, config_attempt=0, company_id=users['employee'].company_id)
        binding = await bind_job(db, job, settings)
        config, _ = await resolve_bound(db, settings, job.company_id, binding, 'report')
        assert binding['report']['effort'] is None and binding['report']['explicitReasoning'] is False
        assert config['parameters'] == {'reasoning': {'effort': 'high'}}
        assert report_model_config(config, binding['report']) is config
