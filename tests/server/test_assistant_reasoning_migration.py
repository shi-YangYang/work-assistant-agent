"""Upgrade real old account rows without changing existing fields."""
import os
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


def test_reasoning_migration_preserves_accounts(monkeypatch):
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'reasoning_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'apps/server/app/migrations'))
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0026_assistant_memory')
        with scoped.begin() as db:
            from app.modules.members.models import Company
            company = db.execute(Company.__table__.insert().values(name='迁移原有公司').returning(Company.id)).scalar_one()
            member = str(uuid4())
            db.execute(text("INSERT INTO company_member (id, created_at, company_id, username, name, role, active) VALUES (:id, now(), :company, 'legacy', '原有账号', 'employee', true)"), {'id': member, 'company': company})
            before = dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id': member}).mappings().one())
        command.upgrade(config, '0027_assistant_reasoning')
        with scoped.connect() as db:
            after = dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id': member}).mappings().one())
            assert after.pop('reasoning_preference') is None and after.pop('reasoning_revision') == 0
            assert after == before
        command.downgrade(config, '0026_assistant_memory')
        with scoped.connect() as db:
            assert 'reasoning_preference' not in {column['name'] for column in inspect(db).get_columns('company_member')}
            assert dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id': member}).mappings().one()) == before
    finally:
        scoped.dispose()
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_direct_migration_preserves_parameters_history_and_account_effort(monkeypatch):
    from copy import deepcopy
    from app.modules.model_services.models import ModelService, ModelServiceRevision, ModelRouting
    from app.modules.members.models import Company, Member
    from app.modules.model_services.schemas import ServiceModel
    from app.modules.model_services.reasoning.legacy import legacy_parameters
    from app.modules.model_services.parameters import request_options, report_model_config
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'direct_reasoning_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'apps/server/app/migrations'))
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0027_assistant_reasoning')
        with scoped.begin() as db:
            company = db.execute(Company.__table__.insert().values(name='迁移参数测试').returning(Company.id)).scalar_one()
            sid, member = str(uuid4()), str(uuid4())
            models = [
                {'id': 'active', 'model': 'legacy-chat', 'protocol': 'chat', 'streaming': True, 'presets': [
                    {'id': 'p-low', 'mode': 'simple', 'value': 'low', 'assistantEffort': 'low'},
                    {'id': 'p-high', 'mode': 'advanced', 'parameters': {'reasoning': {'effort': 'high'}, 'temperature': .7}, 'assistantEffort': 'high'},
                    {'id': 'p-report', 'mode': 'advanced', 'parameters': {}}], 'selectedPresetId': 'p-low'},
                {'id': 'private', 'model': 'private-chat', 'protocol': 'chat', 'presets': [{'id': 'p0', 'mode': 'advanced', 'parameters': {'enable_thinking': False, 'temperature': .3}}, {'id': 'p1', 'mode': 'simple', 'value': 'high', 'assistantEffort': 'high'}], 'selectedPresetId': 'p0'},
                {'id': 'default', 'model': 'default-chat', 'protocol': 'chat', 'presets': [{'id': 'p1', 'mode': 'simple', 'value': 'high', 'assistantEffort': 'high'}], 'selectedPresetId': None},
            ]
            db.execute(ModelService.__table__.insert().values(id=sid, company_id=company, name='迁移服务', base_url='https://example.com/v1', revision=1, models=models))
            rid = db.execute(ModelServiceRevision.__table__.insert().values(company_id=company, service_id=sid, revision=1, name='迁移服务', base_url='https://example.com/v1', models=models, credential='must-not-reencrypt').returning(ModelServiceRevision.id)).scalar_one()
            choice = {'serviceId': sid, 'modelId': 'active', 'presetId': 'p-high', 'streaming': True}
            db.execute(ModelRouting.__table__.insert().values(company_id=company, revision=3, choices={'assistant': choice, 'report': {**choice, 'presetId': 'p-report'}, 'asr': None}))
            db.execute(Member.__table__.insert().values(id=member, company_id=company, username='before', name='原账号', role='employee', active=True, reasoning_preference={'serviceId': sid, 'modelId': 'active', 'presetId': 'p-low'}, reasoning_revision=8))
            before_revision = dict(db.execute(sa_select(ModelServiceRevision.__table__).where(ModelServiceRevision.id == rid)).mappings().one())
        command.upgrade(config, '0028_direct_reasoning')
        command.upgrade(config, '0028_direct_reasoning')
        with scoped.connect() as db:
            converted = db.execute(sa_select(ModelService.models).where(ModelService.id == sid)).scalar_one()
            for model in converted:
                ServiceModel(**model)
                assert not set(model) & {'presets', 'selectedPresetId'}
            assert converted[0]['reasoning']['initial'] == 'high'
            assert request_options(converted[0]) == {'reasoning': {'effort': 'high'}, 'temperature': .7}
            assert request_options(converted[0], 'low') == {'reasoning_effort': 'low'}
            assert converted[1]['reasoning']['efforts'] == [] and request_options(converted[1]) == {'enable_thinking': False, 'temperature': .3}
            assert converted[2]['reasoning']['efforts'] == [] and request_options(converted[2]) == {}
            routing = db.execute(sa_select(ModelRouting.choices).where(ModelRouting.company_id == company)).scalar_one()
            assert 'presetId' not in routing['assistant'] and routing['report']['parameters'] == {} and routing['report']['explicitReasoning'] is True
            config_value = {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-chat', 'parameters': {}}
            assert report_model_config(config_value, routing['report']) is config_value
            preference = db.execute(sa_select(Member.reasoning_preference, Member.reasoning_revision).where(Member.id == member)).one()
            assert preference == ({'serviceId': sid, 'modelId': 'active', 'effort': 'low'}, 9)
            after_revision = dict(db.execute(sa_select(ModelServiceRevision.__table__).where(ModelServiceRevision.id == rid)).mappings().one())
            assert after_revision == before_revision
            assert legacy_parameters(after_revision['models'][0], 'p-high') == {'reasoning': {'effort': 'high'}, 'temperature': .7}
    finally:
        scoped.dispose()
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()


from sqlalchemy import select as sa_select
