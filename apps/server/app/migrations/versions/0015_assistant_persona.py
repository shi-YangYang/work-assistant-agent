"""Preserve existing conversations and message snapshots as professional."""
from alembic import op
import sqlalchemy as sa

revision = '0015_assistant_persona'
down_revision = '0014_voiceprint_cleanup'
branch_labels = depends_on = None


def upgrade():
    for table in ('company_conversation', 'company_message'):
        op.add_column(table, sa.Column('persona_id', sa.String(32), nullable=False, server_default='professional'))


def downgrade():
    for table in ('company_message', 'company_conversation'):
        op.drop_column(table, 'persona_id')
