"""Store assistant execution preferences once per account."""
from alembic import op
import sqlalchemy as sa

revision = '0024_account_execution_mode'
down_revision = '0023_builtin_execution'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_member', sa.Column('execution_mode', sa.String(8), nullable=False, server_default='auto'))
    op.add_column('company_member', sa.Column('full_access_confirmed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('company_member', sa.Column('mode_revision', sa.Integer(), nullable=False, server_default='1'))
    # Do not silently extend a conversation's full access to every conversation.
    # Preserve stricter existing preferences; task/action snapshots stay intact.
    op.execute("UPDATE company_member SET execution_mode = 'ask' WHERE EXISTS (SELECT 1 FROM company_conversation c WHERE c.owner_id = company_member.id AND NOT c.deleted AND c.execution_mode = 'ask')")
    for column in ('execution_mode', 'full_access_confirmed', 'mode_revision'):
        op.drop_column('company_conversation', column)


def downgrade():
    op.add_column('company_conversation', sa.Column('execution_mode', sa.String(8), nullable=False, server_default='auto'))
    op.add_column('company_conversation', sa.Column('full_access_confirmed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('company_conversation', sa.Column('mode_revision', sa.Integer(), nullable=False, server_default='1'))
    op.execute('UPDATE company_conversation c SET execution_mode = m.execution_mode, full_access_confirmed = m.full_access_confirmed, mode_revision = m.mode_revision FROM company_member m WHERE c.owner_id = m.id')
    for column in ('execution_mode', 'full_access_confirmed', 'mode_revision'):
        op.drop_column('company_member', column)
