"""Persistent, owner-scoped business operations and manual work provenance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0010_business_actions'
down_revision = '0009_dingtalk_login'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_work_item', sa.Column('origin', sa.String(16), nullable=False, server_default='suggestion'))
    op.create_table('company_business_action',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('message_id', sa.String(36), nullable=False),
        sa.Column('conversation_id', sa.String(36)),
        sa.Column('step', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('intent_key', sa.String(64), nullable=False),
        sa.Column('params', JSONB(), nullable=False),
        sa.Column('access', JSONB(), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('result', JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('message_id', 'step'),
        sa.UniqueConstraint('message_id', 'intent_key'))
    for field in ('company_id', 'owner_id', 'message_id', 'conversation_id'):
        op.create_index('ix_company_business_action_' + field, 'company_business_action', [field])


def downgrade():
    raise RuntimeError('Business receipts must be preserved when rolling back application code.')
