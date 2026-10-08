"""Optional account effort preferences; existing model revisions stay immutable."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0027_assistant_reasoning'
down_revision = '0026_assistant_memory'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_member', sa.Column('reasoning_preference', postgresql.JSONB(), nullable=True))
    op.add_column('company_member', sa.Column('reasoning_revision', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('company_member', 'reasoning_revision')
    op.drop_column('company_member', 'reasoning_preference')
