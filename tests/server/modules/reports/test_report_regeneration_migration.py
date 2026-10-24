"""Real PostgreSQL migration preserves tombstones and refuses destructive rollback."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.modules.members.models import Company, Member
from app.modules.reports.models import Report, ReportEligibility


def test_regeneration_upgrade_backfill_unique_index_and_guarded_downgrade(monkeypatch):
    Settings()
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'report_regeneration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[4] / 'apps/server/app/migrations'))
    instant = datetime(2026, 10, 19, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0032_default_full_execution')
        with scoped.begin() as connection:
            company = connection.execute(Company.__table__.insert().values(name='报告迁移测试').returning(Company.id)).scalar_one()
            old_obligations = Table('company_report_obligation', MetaData(), autoload_with=connection)
            owners, report_ids = {}, {}
            for scenario in ('deleted', 'revoked', 'missing', 'active'):
                owner = connection.execute(Member.__table__.insert().values(company_id=company, username=scenario, name=scenario, role='employee').returning(Member.id)).scalar_one()
                owners[scenario] = owner
                report_id = connection.execute(Report.__table__.insert().values(company_id=company, owner_id=owner, kind='weekly', period='2026-10-19', period_end='2026-10-25', timezone='UTC', deleted=scenario != 'active', content={'completed': '保留的历史'}, source_ids=[]).returning(Report.id)).scalar_one()
                report_ids[scenario] = report_id
                if scenario != 'missing':
                    connection.execute(ReportEligibility.__table__.insert().values(company_id=company, owner_id=owner, starts_at=instant - timedelta(days=1), ends_at=instant + timedelta(days=1) if scenario == 'revoked' else None))
                if scenario == 'revoked':
                    connection.execute(ReportEligibility.__table__.insert().values(company_id=company, owner_id=owner, starts_at=instant + timedelta(days=2)))
                connection.execute(old_obligations.insert().values(id=str(uuid4()), company_id=company, owner_id=owner, created_at=instant, kind='weekly', period='2026-10-19', period_end='2026-10-25', timezone='UTC', rule_revision=1, generate_at=instant, deadline_at=instant + timedelta(days=1), reminders=True, before_minutes=30, state='pending' if scenario == 'active' else 'cancelled', report_id=report_id, generation_checked=True))
            before = list(connection.execute(select(Report.__table__).order_by(Report.id)).mappings())
        command.upgrade(config, '0033_report_regeneration')
        with scoped.connect() as connection:
            assert list(connection.execute(select(Report.__table__).order_by(Report.id)).mappings()) == before
            reasons = dict(connection.execute(text('SELECT owner_id, cancel_reason FROM company_report_obligation')).all())
            assert reasons == {owners['deleted']: 'report_deleted', owners['revoked']: 'unknown', owners['missing']: 'unknown', owners['active']: None}
            index = connection.scalar(text("SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'uq_report_active_period'"))
            assert 'UNIQUE INDEX' in index and 'deleted IS FALSE' in index
        # The old schema can still be restored before any duplicate history exists.
        command.downgrade(config, '0032_default_full_execution')
        with scoped.connect() as connection:
            assert list(connection.execute(select(Report.__table__).order_by(Report.id)).mappings()) == before
            assert connection.scalar(text("SELECT count(*) FROM information_schema.table_constraints WHERE table_schema = current_schema() AND constraint_name = 'company_report_owner_id_kind_period_key'")) == 1
        command.upgrade(config, '0033_report_regeneration')
        values = dict(company_id=company, owner_id=owners['deleted'], kind='weekly', period='2026-10-19', period_end='2026-10-25', timezone='UTC', content={}, source_ids=[])
        with scoped.begin() as connection:
            connection.execute(Report.__table__.insert().values(**values, deleted=True))
            connection.execute(Report.__table__.insert().values(**values, deleted=False))
        with pytest.raises(IntegrityError):
            with scoped.begin() as connection:
                connection.execute(Report.__table__.insert().values(**values, deleted=False))
        with pytest.raises(RuntimeError, match='同周期已有多条报告历史'):
            command.downgrade(config, '0032_default_full_execution')
        with scoped.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0033_report_regeneration'
            assert connection.scalar(text('SELECT count(*) FROM company_report')) == len(before) + 2
            assert connection.scalar(select(Report.content).where(Report.id == report_ids['deleted'])) == {'completed': '保留的历史'}
            assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'company_report_obligation' AND column_name = 'cancel_reason'")) == 1
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
