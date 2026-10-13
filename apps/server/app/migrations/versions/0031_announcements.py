"""Company announcements and versioned personal read receipts."""
from alembic import op
import sqlalchemy as sa

revision = '0031_announcements'
down_revision = '0030_image_provider_result'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_announcement',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('title', sa.String(100), nullable=False),
        sa.Column('markdown', sa.Text(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.String(36), sa.ForeignKey('company_member.id', ondelete='SET NULL')),
        sa.Column('author_name', sa.String(200), nullable=False),
        sa.Column('editor_id', sa.String(36), sa.ForeignKey('company_member.id', ondelete='SET NULL')),
        sa.Column('editor_name', sa.String(200), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('published', 'withdrawn')", name='ck_announcement_state'),
        sa.CheckConstraint('revision >= 1', name='ck_announcement_revision'))
    op.create_index('ix_announcement_company_state_created', 'company_announcement', ['company_id', 'state', 'created_at', 'id'])
    op.create_table('company_announcement_read',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('announcement_id', sa.String(36), sa.ForeignKey('company_announcement.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reader_id', sa.String(36), sa.ForeignKey('company_member.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('announcement_id', 'reader_id'))
    op.create_index('ix_announcement_read_company_reader', 'company_announcement_read', ['company_id', 'reader_id'])


def downgrade():
    # Deployment rollbacks retain announcements; table removal is an explicit
    # destructive schema operation, never part of application rollback.
    raise RuntimeError('Announcement data must be retained when rolling back the application')
