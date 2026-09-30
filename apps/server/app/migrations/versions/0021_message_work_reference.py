"""Keep the explicit work reference with its original user message."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0021_message_work_reference'
down_revision = '0020_work_revision_origin'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_message', sa.Column('work_reference', postgresql.JSONB(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('company_message', 'work_reference')
