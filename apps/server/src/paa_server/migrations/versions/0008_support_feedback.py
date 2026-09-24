"""Standalone support feedback; keep business records and model context untouched."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0008_support_feedback'
down_revision = '0007_report_obligations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'company_support_feedback',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('diagnostics', JSONB(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('handling_note', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_company_support_feedback_company_id', 'company_support_feedback', ['company_id'])
    op.create_index('ix_company_support_feedback_owner_id', 'company_support_feedback', ['owner_id'])
    op.create_index('ix_support_feedback_company_state_created', 'company_support_feedback', ['company_id', 'state', 'created_at'])
    op.create_index('ix_support_feedback_owner_created', 'company_support_feedback', ['owner_id', 'created_at'])


def downgrade():
    raise RuntimeError('保留问题反馈与处理记录；回滚请只回滚应用，不删除持久记录。')
