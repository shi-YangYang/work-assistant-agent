"""Keep deleted report identities while allowing explicit period regeneration."""
from alembic import op
import sqlalchemy as sa

revision = '0033_report_regeneration'
down_revision = '0032_default_full_execution'
branch_labels = depends_on = None


def upgrade():
    op.create_index('uq_report_active_period', 'company_report', ['owner_id', 'kind', 'period'], unique=True, postgresql_where=sa.text('deleted IS FALSE'))
    op.drop_constraint('company_report_owner_id_kind_period_key', 'company_report', type_='unique')
    op.add_column('company_report_obligation', sa.Column('cancel_reason', sa.String(24), nullable=True))
    # A deleted link alone is insufficient: eligibility may have been revoked
    # before/after deletion. Unknown legacy cancellations stay cancelled.
    op.execute("""
        UPDATE company_report_obligation AS o SET cancel_reason = CASE
          WHEN EXISTS (
            SELECT 1 FROM company_report r JOIN company_member m ON m.id = r.owner_id
            WHERE r.id = o.report_id AND r.owner_id = o.owner_id
              AND r.company_id = o.company_id AND r.deleted AND m.active AND m.role = 'employee'
          ) AND EXISTS (
            SELECT 1 FROM company_report_eligibility e
            WHERE e.owner_id = o.owner_id AND e.company_id = o.company_id
              AND e.starts_at <= (o.period::date::timestamp AT TIME ZONE o.timezone)
              AND e.ends_at IS NULL
          ) AND NOT EXISTS (
            SELECT 1 FROM company_report_eligibility e
            WHERE e.owner_id = o.owner_id AND e.company_id = o.company_id
              AND e.ends_at >= (o.period::date::timestamp AT TIME ZONE o.timezone)
          ) THEN 'report_deleted' ELSE 'unknown' END
        WHERE o.state = 'cancelled'
    """)


def downgrade():
    # Fail before changing schema; never erase tombstones to satisfy old code.
    duplicates = op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM company_report GROUP BY owner_id, kind, period HAVING count(*) > 1)'))
    if duplicates:
        raise RuntimeError('同周期已有多条报告历史，不能恢复旧唯一约束；请按备份回滚流程恢复，不得删除历史记录。')
    op.create_unique_constraint('company_report_owner_id_kind_period_key', 'company_report', ['owner_id', 'kind', 'period'])
    op.drop_index('uq_report_active_period', table_name='company_report')
    op.drop_column('company_report_obligation', 'cancel_reason')
