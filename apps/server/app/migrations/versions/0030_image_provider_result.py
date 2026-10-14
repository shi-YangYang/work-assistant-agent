"""Retain synchronous image receipts without changing existing async operations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0030_image_provider_result'
down_revision = '0029_image_generation'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_image_generation', sa.Column('provider_result', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.alter_column('company_image_generation', 'provider_result', server_default=None)


def downgrade():
    op.drop_column('company_image_generation', 'provider_result')
