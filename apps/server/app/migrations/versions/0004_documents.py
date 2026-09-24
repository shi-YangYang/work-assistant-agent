"""Private document extraction; old media retain their identity and no parse state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004_documents'
down_revision = '0003_conversations'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('company_message', sa.Column('citations', postgresql.JSONB(), nullable=False, server_default='[]'))
    for column in (
        sa.Column('extraction_status', sa.String(16), nullable=False, server_default='none'),
        sa.Column('extraction_revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('parser_version', sa.String(80), nullable=False, server_default=''),
        sa.Column('extraction_info', postgresql.JSONB(), nullable=False, server_default='{}'),
    ):
        op.add_column('company_attachment', column)
    op.create_table('company_document_chunk',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('attachment_id', sa.String(36), sa.ForeignKey('company_attachment.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('location', sa.String(300), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.UniqueConstraint('attachment_id', 'revision', 'ordinal'))
    for field in ('company_id', 'owner_id', 'attachment_id'):
        op.create_index('ix_company_document_chunk_' + field, 'company_document_chunk', [field])


def downgrade():
    op.drop_table('company_document_chunk')
    for column in ('extraction_status', 'extraction_revision', 'parser_version', 'extraction_info'):
        op.drop_column('company_attachment', column)
    op.drop_column('company_message', 'citations')
