"""Persist explicit voiceprint file deletion intents; leave legacy data intact."""
from alembic import op
import sqlalchemy as sa

revision = '0014_voiceprint_cleanup'
down_revision = '0013_drop_password_change'
branch_labels = depends_on = None


def upgrade():
    op.create_table('company_voiceprint_cleanup',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('member_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('path', sa.String(80), nullable=False, unique=True),
        sa.Column('error', sa.String(220), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False))
    op.create_index('ix_company_voiceprint_cleanup_company_id', 'company_voiceprint_cleanup', ['company_id'])


def downgrade():
    # Refuse to silently discard unfinished file deletion requests.
    pending = op.get_bind().scalar(sa.text('SELECT count(*) FROM company_voiceprint_cleanup'))
    if pending:
        raise RuntimeError('Finish pending voiceprint cleanup before rollback.')
    op.drop_table('company_voiceprint_cleanup')
