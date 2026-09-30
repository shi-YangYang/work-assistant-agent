"""Conversation execution policy and durable user questions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0019_assistant_interactions'
down_revision = '0018_conversation_task_state'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_conversation', sa.Column('execution_mode', sa.String(8), nullable=False, server_default='auto'))
    op.add_column('company_conversation', sa.Column('full_access_confirmed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('company_conversation', sa.Column('mode_revision', sa.Integer(), nullable=False, server_default='1'))
    for column in [sa.Column('execution_mode', sa.String(8), nullable=False, server_default='auto'), sa.Column('mode_revision', sa.Integer(), nullable=False, server_default='1'), sa.Column('approval_reason', sa.String(120), nullable=False, server_default=''), sa.Column('continuation', postgresql.JSONB(), nullable=False, server_default='{}')]:
        op.add_column('company_business_action', column)
    op.create_table('company_assistant_interaction',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('conversation_id', sa.String(36), nullable=False),
        sa.Column('message_id', sa.String(36), nullable=False),
        sa.Column('job_id', sa.String(36), nullable=False),
        sa.Column('task_id', sa.String(36), nullable=False),
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('source_revision', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('questions', postgresql.JSONB(), nullable=False),
        sa.Column('answers', postgresql.JSONB(), nullable=False),
        sa.Column('sources', postgresql.JSONB(), nullable=False),
        sa.Column('access', postgresql.JSONB(), nullable=False),
        sa.Column('continuation', postgresql.JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('task_id', 'key', name='uq_assistant_interaction_task_key'))
    for column in ('company_id', 'owner_id', 'conversation_id', 'message_id'):
        op.create_index('ix_company_assistant_interaction_' + column, 'company_assistant_interaction', [column])


def downgrade():
    op.drop_table('company_assistant_interaction')
    for column in ('continuation', 'approval_reason', 'mode_revision', 'execution_mode'):
        op.drop_column('company_business_action', column)
    op.drop_column('company_conversation', 'full_access_confirmed')
    op.drop_column('company_conversation', 'mode_revision')
    op.drop_column('company_conversation', 'execution_mode')
