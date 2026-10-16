"""New accounts use autonomous execution; existing preferences stay unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '0032_default_full_execution'
down_revision = '0031_announcements'
branch_labels = depends_on = None


def upgrade():
    # Change only the insertion default, never existing accounts or task snapshots.
    # full_access_confirmed still records an explicit user acknowledgement.
    op.alter_column('company_member', 'execution_mode', existing_type=sa.String(8), server_default='full')


def downgrade():
    op.alter_column('company_member', 'execution_mode', existing_type=sa.String(8), server_default='auto')
