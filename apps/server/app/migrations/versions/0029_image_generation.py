"""Private durable image operations (additive)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0029_image_generation'
down_revision = '0028_direct_reasoning'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_image_generation',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('company_job.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('company_conversation.id'), nullable=False),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('company_message.id'), nullable=False),
        sa.Column('operation', sa.Integer, nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('fence', sa.Integer, nullable=False), sa.Column('state', sa.String(24), nullable=False),
        sa.Column('task_id', sa.String(200)), sa.Column('request_id', sa.String(200)),
        sa.Column('usage_id', sa.String(36), sa.ForeignKey('company_model_usage.id')),
        sa.Column('binding', JSONB, nullable=False), sa.Column('request', JSONB, nullable=False),
        sa.Column('sources', JSONB, nullable=False), sa.Column('files', JSONB, nullable=False), sa.Column('result', JSONB, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('message_id', 'operation'), sa.UniqueConstraint('message_id', 'fingerprint'))
    for column in ('company_id', 'owner_id', 'job_id', 'conversation_id', 'message_id'):
        op.create_index('ix_company_image_generation_' + column, 'company_image_generation', [column])


def downgrade():
    op.drop_table('company_image_generation')
