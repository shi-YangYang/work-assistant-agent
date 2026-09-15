"""Persist future report arrangements, eligibility and reminders without old debt."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_report_obligations'
down_revision = '0006_feedback_usage'
branch_labels = None
depends_on = None


def base(owned=True):
    columns = [sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False)]
    if owned:
        columns.append(sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False))
    return columns


def upgrade():
    op.create_table('company_report_schedule', *base(False), sa.Column('kind', sa.String(10), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('timezone', sa.String(80), nullable=False), sa.Column('rule', JSONB(), nullable=False), sa.Column('effective_period', sa.String(10), nullable=False), sa.Column('next_period', sa.String(10), nullable=False), sa.UniqueConstraint('company_id', 'kind', 'revision'))
    op.create_table('company_report_eligibility', *base(), sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False), sa.Column('ends_at', sa.DateTime(timezone=True)))
    op.create_table('company_report_obligation', *base(), sa.Column('kind', sa.String(10), nullable=False), sa.Column('period', sa.String(10), nullable=False), sa.Column('period_end', sa.String(10), nullable=False), sa.Column('timezone', sa.String(80), nullable=False), sa.Column('rule_revision', sa.Integer(), nullable=False), sa.Column('generate_at', sa.DateTime(timezone=True), nullable=False), sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False), sa.Column('reminders', sa.Boolean(), nullable=False), sa.Column('before_minutes', sa.Integer(), nullable=False), sa.Column('state', sa.String(16), nullable=False), sa.Column('report_id', sa.String(36), sa.ForeignKey('company_report.id')), sa.Column('submitted_at', sa.DateTime(timezone=True)), sa.Column('generation_checked', sa.Boolean(), nullable=False), sa.UniqueConstraint('owner_id', 'kind', 'period'))
    op.create_table('company_report_notification', *base(), sa.Column('obligation_id', sa.String(36), sa.ForeignKey('company_report_obligation.id'), nullable=False, unique=True), sa.Column('stage', sa.String(16), nullable=False), sa.Column('read_at', sa.DateTime(timezone=True)), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for table in ('company_report_schedule', 'company_report_eligibility', 'company_report_obligation', 'company_report_notification'):
        op.create_index('ix_' + table + '_company_id', table, ['company_id'])
        if table != 'company_report_schedule':
            op.create_index('ix_' + table + '_owner_id', table, ['owner_id'])
    op.create_index('ix_obligation_period', 'company_report_obligation', ['company_id', 'kind', 'period', 'owner_id'])
    db = op.get_bind()
    instant = datetime.now(timezone.utc)
    for company in db.execute(sa.text('SELECT id, rules, revision FROM company')).mappings():
        local = instant.astimezone(ZoneInfo(company['rules']['timezone'])).date()
        for kind in ('daily', 'weekly'):
            effective = (local + timedelta(days=1 if kind == 'daily' else 7-local.weekday())).isoformat()
            db.execute(sa.text('INSERT INTO company_report_schedule (id, created_at, company_id, kind, revision, timezone, rule, effective_period, next_period) VALUES (:id, :now, :company, :kind, :revision, :zone, CAST(:rule AS jsonb), :effective, :effective)'), {'id': str(uuid4()), 'now': instant, 'company': company['id'], 'kind': kind, 'revision': company['revision'], 'zone': company['rules']['timezone'], 'rule': json.dumps(company['rules'][kind]), 'effective': effective})
    for member in db.execute(sa.text("SELECT id, company_id FROM company_member WHERE active AND role = 'employee'")).mappings():
        db.execute(sa.text('INSERT INTO company_report_eligibility (id, created_at, company_id, owner_id, starts_at) VALUES (:id, :now, :company, :owner, :now)'), {'id': str(uuid4()), 'now': instant, 'company': member['company_id'], 'owner': member['id']})


def downgrade():
    raise RuntimeError('保留安排、提交和提醒历史；回滚请只回滚应用，不删除持久记录。')
