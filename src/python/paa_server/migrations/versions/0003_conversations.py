"""Persistent business conversations and non-resurrectable deletion markers."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '0003_conversations'
down_revision = '0002_model_services'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('company_conversation',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('company_id', 'owner_id'):
        op.create_index('ix_company_conversation_' + column, 'company_conversation', [column])
    op.add_column('company_message', sa.Column('conversation_id', sa.String(36), sa.ForeignKey('company_conversation.id'), nullable=True))
    op.create_index('ix_company_message_conversation_id', 'company_message', ['conversation_id'])
    for table in ('company_message', 'company_attachment', 'company_work_item', 'company_report'):
        op.add_column(table, sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()))
    connection = op.get_bind()
    owners = connection.execute(sa.text('SELECT company_id, owner_id, MIN(created_at) AS first, MAX(created_at) AS last FROM company_message GROUP BY company_id, owner_id')).mappings().all()
    for owner in owners:
        identifier = str(uuid4())
        connection.execute(sa.text("INSERT INTO company_conversation (id, company_id, owner_id, title, created_at, updated_at) VALUES (:id, :company_id, :owner_id, '默认会话', :first, :last)"), {**owner, 'id': identifier})
        connection.execute(sa.text('UPDATE company_message SET conversation_id = :id WHERE owner_id = :owner_id AND company_id = :company_id'), {**owner, 'id': identifier})


def downgrade():
    raise RuntimeError('Restore the matching pre-migration backup and application; destructive downgrade is disabled')
