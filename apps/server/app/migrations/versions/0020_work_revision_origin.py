"""Record the actor path for each work revision, independently of public sources."""
from alembic import op
import sqlalchemy as sa

revision = '0020_work_revision_origin'
down_revision = '0019_assistant_interactions'
branch_labels = depends_on = None


def upgrade():
    op.add_column('company_work_revision', sa.Column('origin', sa.String(24), nullable=False, server_default='unknown'))
    # Existing writes always retained either public sources or a private
    # publication reference. Do not expose those private IDs in the history API.
    op.execute("""UPDATE company_work_revision SET origin = CASE
        WHEN jsonb_array_length(source_ids) > 0
          OR jsonb_array_length(COALESCE(publication->'originMessageIds', '[]'::jsonb)) > 0
        THEN 'assistant' ELSE 'manual' END""")
    op.execute("""UPDATE company_work_revision AS r SET origin = 'assistant_confirmed'
        FROM company_progress_draft AS d
        WHERE d.status = 'confirmed' AND d.work_id = r.work_id
          AND d.company_id = r.company_id AND d.owner_id = r.owner_id
          AND r.revision = COALESCE(d.base_revision, 0) + 1
          AND (r.source_ids ? d.message_id OR (r.publication->'originMessageIds') ? d.message_id)""")


def downgrade():
    op.drop_column('company_work_revision', 'origin')
