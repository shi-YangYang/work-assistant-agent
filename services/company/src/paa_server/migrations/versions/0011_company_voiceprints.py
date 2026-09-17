"""Private voiceprint enrollments and browser-approved desktop sessions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0011_company_voiceprints'
down_revision = '0010_business_actions'
branch_labels = depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('company_desktop_authorization', *common(),
        sa.Column('request_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('challenge', sa.String(43), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id')),
        sa.Column('member_id', sa.String(36), sa.ForeignKey('company_member.id')),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('company_session.id', ondelete='CASCADE')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('polled_at', sa.DateTime(timezone=True)))
    op.create_index('ix_company_desktop_authorization_expires_at', 'company_desktop_authorization', ['expires_at'])
    op.create_table('company_desktop_session', *common(),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('member_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('company_session.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    for field in ('company_id', 'member_id', 'session_id', 'expires_at'):
        op.create_index('ix_company_desktop_session_' + field, 'company_desktop_session', [field])
    op.create_table('company_voiceprint', *common(),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('member_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False, unique=True),
        sa.Column('state', sa.String(16), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.String(120), nullable=False), sa.Column('templates', JSONB(), nullable=False),
        sa.Column('ready_path', sa.String(80), nullable=False), sa.Column('pending_path', sa.String(80), nullable=False),
        sa.Column('filename', sa.String(160), nullable=False), sa.Column('error', sa.String(220), nullable=False),
        sa.Column('speech_seconds', sa.Integer(), nullable=False),
        sa.Column('consent_by', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False),
        sa.Column('consent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True)))
    op.create_index('ix_company_voiceprint_company_id', 'company_voiceprint', ['company_id'])


def downgrade():
    raise RuntimeError('Private enrollment originals must be deliberately retained or deleted before rollback.')
