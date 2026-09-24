"""Remove accounts without erasing their business history."""
from alembic import op
import sqlalchemy as sa

revision = '0012_member_deletion'
down_revision = '0011_company_voiceprints'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_member', sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint('ck_company_member_deleted_inactive', 'company_member', 'NOT deleted OR NOT active')


def downgrade():
    op.drop_constraint('ck_company_member_deleted_inactive', 'company_member', type_='check')
    op.drop_column('company_member', 'deleted')
