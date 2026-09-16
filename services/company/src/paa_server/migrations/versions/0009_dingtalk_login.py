"""Browser OAuth identity links; preserve existing local credentials."""
from alembic import op
import sqlalchemy as sa

revision = '0009_dingtalk_login'
down_revision = '0008_support_feedback'
branch_labels = None
depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False)]


def upgrade():
    op.alter_column('company_member', 'password_hash', existing_type=sa.Text(), nullable=True)
    op.create_table('company_dingtalk_config', *common(),
        sa.Column('corp_id', sa.String(128), nullable=False),
        sa.Column('client_id', sa.String(128), nullable=False),
        sa.Column('credential', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('company_id'))
    op.create_table('company_dingtalk_identity', *common(),
        sa.Column('member_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False, unique=True),
        sa.Column('corp_id', sa.String(128), nullable=False),
        sa.Column('client_id', sa.String(128), nullable=False),
        sa.Column('union_id', sa.String(256), nullable=False),
        sa.Column('user_id', sa.String(256), nullable=False),
        sa.UniqueConstraint('company_id', 'corp_id', 'client_id', 'union_id'),
        sa.UniqueConstraint('company_id', 'corp_id', 'client_id', 'user_id'))
    op.create_index('ix_company_dingtalk_identity_company_id', 'company_dingtalk_identity', ['company_id'])
    op.create_table('company_dingtalk_authorization', *common(),
        sa.Column('state_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('browser_hash', sa.String(64), nullable=False),
        sa.Column('config_revision', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(16), nullable=False),
        sa.Column('member_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=True),
        sa.Column('session_id', sa.String(36), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('proof_hash', sa.String(64), nullable=True, unique=True),
        sa.Column('proof_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('proof_used_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_company_dingtalk_authorization_company_id', 'company_dingtalk_authorization', ['company_id'])
    op.create_index('ix_company_dingtalk_authorization_expires_at', 'company_dingtalk_authorization', ['expires_at'])


def downgrade():
    raise RuntimeError('钉钉账号可能没有本地密码；请先安排登录迁移，不自动删除身份或强制恢复非空密码约束。')
