"""Private versioned assistant results and explicitly selected publication."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0016_assistant_deliverables'
down_revision = '0015_assistant_persona'
branch_labels = depends_on = None


def owned():
    return [sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False), sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False)]


def upgrade():
    op.create_table('company_deliverable', *owned(), sa.Column('conversation_id', sa.String(36), sa.ForeignKey('company_conversation.id'), nullable=False), sa.Column('title', sa.String(200), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('access', postgresql.JSONB(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('company_deliverable_revision', *owned(), sa.Column('deliverable_id', sa.String(36), sa.ForeignKey('company_deliverable.id'), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('message_id', sa.String(36), sa.ForeignKey('company_message.id'), nullable=False), sa.Column('step', sa.Integer(), nullable=False), sa.Column('title', sa.String(200), nullable=False), sa.Column('body', sa.Text(), nullable=False), sa.Column('items', postgresql.JSONB(), nullable=False), sa.Column('digest', sa.String(64), nullable=False), sa.UniqueConstraint('deliverable_id', 'revision'), sa.UniqueConstraint('message_id', 'step'))
    op.create_table('company_deliverable_link', *owned(), sa.Column('deliverable_id', sa.String(36), sa.ForeignKey('company_deliverable.id'), nullable=False), sa.Column('item_id', sa.String(36), nullable=False), sa.Column('work_id', sa.String(36), sa.ForeignKey('company_work_item.id'), nullable=False), sa.Column('source_revision', sa.Integer(), nullable=False), sa.Column('action_id', sa.String(36), sa.ForeignKey('company_business_action.id'), nullable=False, unique=True))
    for table, columns in {'company_deliverable': ['company_id', 'owner_id', 'conversation_id'], 'company_deliverable_revision': ['company_id', 'owner_id', 'deliverable_id', 'message_id'], 'company_deliverable_link': ['company_id', 'owner_id', 'deliverable_id', 'work_id']}.items():
        for column in columns:
            op.create_index('ix_' + table + '_' + column, table, [column])
    # Historical published sources retain their existing access rules.
    op.add_column('company_message', sa.Column('private_context', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('company_message', 'private_context', server_default=sa.true())
    op.add_column('company_message', sa.Column('deliverable_reference', postgresql.JSONB(), nullable=False, server_default='{}'))
    op.add_column('company_work_revision', sa.Column('publication', postgresql.JSONB(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('company_work_revision', 'publication')
    op.drop_column('company_message', 'deliverable_reference')
    op.drop_column('company_message', 'private_context')
    for table in ('company_deliverable_link', 'company_deliverable_revision', 'company_deliverable'):
        op.drop_table(table)
