"""Typed sandbox request snapshots alongside historical Python code."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0023_builtin_execution'
down_revision = '0022_sandbox_deliverables'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_sandbox_execution', sa.Column('request', postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column('company_sandbox_execution', 'request')
