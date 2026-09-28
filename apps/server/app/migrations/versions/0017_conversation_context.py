"""Conversation reference snapshots; existing histories rebuild lazily."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0017_conversation_context'
down_revision = '0016_assistant_deliverables'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_conversation_context',
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('company_conversation.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('invalidation_version', sa.Integer(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('company_id', 'owner_id'):
        op.create_index('ix_company_conversation_context_' + column, 'company_conversation_context', [column])


def downgrade():
    op.drop_table('company_conversation_context')
