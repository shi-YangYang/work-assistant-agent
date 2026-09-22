"""Remove the retired forced password change flag."""
from alembic import op
import sqlalchemy as sa

revision = '0013_drop_password_change'
down_revision = '0012_member_deletion'
branch_labels = depends_on = None


def upgrade():
    op.drop_column('company_member', 'must_change_password')


def downgrade():
    # Restored accounts remain usable; deleted flag values are not recoverable.
    op.add_column('company_member', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('company_member', 'must_change_password', server_default=None)
