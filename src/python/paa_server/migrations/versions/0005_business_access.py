"""Versioned team evidence and private follow-up links; old records stay private."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005_business_access'
down_revision = '0004_documents'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('company_job', 'company_message', 'company_work_item', 'company_work_revision', 'company_progress_draft'):
        op.add_column(table, sa.Column('access', postgresql.JSONB(), nullable=False, server_default='{}'))
    for table in ('company_work_item', 'company_work_revision', 'company_progress_draft'):
        op.add_column(table, sa.Column('business_links', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.create_index('ix_company_job_access', 'company_job', ['access'], postgresql_using='gin')
    op.create_index('ix_company_message_access', 'company_message', ['access'], postgresql_using='gin')


def downgrade():
    op.drop_index('ix_company_message_access')
    op.drop_index('ix_company_job_access')
    for table in ('company_work_item', 'company_work_revision', 'company_progress_draft'):
        op.drop_column(table, 'business_links')
    for table in ('company_job', 'company_message', 'company_work_item', 'company_work_revision', 'company_progress_draft'):
        op.drop_column(table, 'access')
