"""Private generated files and durable isolated execution receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0022_sandbox_deliverables'
down_revision = '0021_message_work_reference'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_deliverable_revision', sa.Column('files', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.create_table('company_sandbox_execution',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('key', sa.String(64), nullable=False, unique=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('company_job.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('company_conversation.id'), nullable=False),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('company_message.id'), nullable=False),
        sa.Column('fence', sa.Integer(), nullable=False), sa.Column('state', sa.String(16), nullable=False),
        sa.Column('code', sa.Text(), nullable=False), sa.Column('sources', postgresql.JSONB(), nullable=False), sa.Column('result', postgresql.JSONB(), nullable=False))
    for name in ('company_id', 'owner_id', 'job_id', 'conversation_id', 'message_id'):
        op.create_index('ix_company_sandbox_execution_' + name, 'company_sandbox_execution', [name])


def downgrade():
    op.drop_table('company_sandbox_execution')
    op.drop_column('company_deliverable_revision', 'files')
