"""Durable per-conversation intent and task-scoped operation receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0018_conversation_task_state'
down_revision = '0017_conversation_context'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_conversation_task_state',
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('company_conversation.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('company_id', 'owner_id'):
        op.create_index('ix_company_conversation_task_state_' + column, 'company_conversation_task_state', [column])
    op.add_column('company_business_action', sa.Column('task_id', sa.String(36), nullable=True))
    op.add_column('company_business_action', sa.Column('task_item_key', sa.String(64), nullable=True))
    op.create_unique_constraint('uq_business_action_task_item', 'company_business_action', ['task_id', 'task_item_key'])


def downgrade():
    op.drop_constraint('uq_business_action_task_item', 'company_business_action', type_='unique')
    op.drop_column('company_business_action', 'task_item_key')
    op.drop_column('company_business_action', 'task_id')
    op.drop_table('company_conversation_task_state')
