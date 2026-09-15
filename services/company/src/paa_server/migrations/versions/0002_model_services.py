"""Company model revisions and credential-free job bindings (additive migration)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002_model_services'
down_revision = '0001_company'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('company', sa.Column('environment_models', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Only companies present during upgrade may retain the previous environment mode.
    op.execute('UPDATE company SET environment_models = TRUE')
    op.add_column('company_job', sa.Column('model_binding', JSONB(), nullable=True))
    op.add_column('company_job', sa.Column('config_attempt', sa.Integer(), nullable=False, server_default='0'))
    op.alter_column('company_model_usage', 'job_id', nullable=True)
    record = lambda: [sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]
    company = lambda: sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False)
    op.create_table('company_model_service', *record(), company(), sa.Column('name', sa.String(80), nullable=False), sa.Column('base_url', sa.String(2048), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('models', JSONB(), nullable=False), sa.Column('internal', sa.Boolean(), nullable=False), sa.Column('revoked', sa.Boolean(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('company_model_service_revision', *record(), company(), sa.Column('service_id', sa.String(36), sa.ForeignKey('company_model_service.id'), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('name', sa.String(80), nullable=False), sa.Column('base_url', sa.String(2048), nullable=False), sa.Column('models', JSONB(), nullable=False), sa.Column('credential', sa.Text(), nullable=False), sa.UniqueConstraint('service_id', 'revision'))
    op.create_table('company_model_routing', sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), primary_key=True), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('choices', JSONB(), nullable=False))
    op.create_table('company_model_check', *record(), company(), sa.Column('actor_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('result', JSONB(), nullable=False))
    for name in ('company_model_service', 'company_model_service_revision', 'company_model_check'):
        op.create_index('ix_' + name + '_company_id', name, ['company_id'])


def downgrade():
    raise RuntimeError('Restore the matching database backup, key file and application; destructive downgrade is disabled')
