"""Non-destructive request accounting and bounded job feedback."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006_feedback_usage'
down_revision = '0005_business_access'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('company_job', sa.Column('feedback', postgresql.JSONB(), nullable=False, server_default='{}'))
    op.add_column('company_model_usage', sa.Column('status', sa.String(16), nullable=False, server_default='legacy'))
    for name, kind in [('service_id',sa.String(36)), ('service_name',sa.String(80)), ('model_name',sa.String(200)), ('job_attempt',sa.Integer()), ('job_fence',sa.Integer()), ('started_at',sa.DateTime(timezone=True)), ('finished_at',sa.DateTime(timezone=True)), ('elapsed_ms',sa.Integer()), ('actual_input_tokens',sa.Integer()), ('actual_output_tokens',sa.Integer()), ('error_code',sa.String(40)), ('error_message',sa.String(300))]:
        op.add_column('company_model_usage', sa.Column(name, kind, nullable=True))
    op.create_index('ix_usage_company_date_id','company_model_usage',['company_id','created_at','id'])
    op.create_index('ix_work_owner_updated_id','company_work_item',['company_id','owner_id','updated_at','id'])
    op.create_index('ix_work_revision_period','company_work_revision',['company_id','created_at','work_id'])
    op.create_index('ix_report_revision_period','company_report_revision',['company_id','created_at','report_id'])


def downgrade():
    # Rollback application code while retaining additive columns and accounting.
    # Removing them would destroy historical data; no destructive downgrade.
    raise RuntimeError('此迁移保留历史调用与反馈数据；回滚请仅回滚应用代码，不降低数据库版本。')
