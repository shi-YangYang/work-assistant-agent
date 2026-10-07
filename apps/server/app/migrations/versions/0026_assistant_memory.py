"""Private account memory; existing accounts remain enabled and empty."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0026_assistant_memory'
down_revision = '0025_work_records'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_assistant_memory',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('generation', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('company_id', 'owner_id'))
    op.create_index('ix_company_assistant_memory_company_id', 'company_assistant_memory', ['company_id'])
    op.create_index('ix_company_assistant_memory_owner_id', 'company_assistant_memory', ['owner_id'])


def downgrade():
    op.drop_table('company_assistant_memory')
