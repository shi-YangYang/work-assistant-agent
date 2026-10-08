"""Convert active model settings to direct efforts, preserving immutable history."""
from copy import deepcopy
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.modules.model_services.reasoning.legacy import direct_model, migrated_choices, legacy_reference_effort

revision = '0028_direct_reasoning'
down_revision = '0027_assistant_reasoning'
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    services = sa.table('company_model_service', sa.column('id', sa.String), sa.column('company_id', sa.String), sa.column('models', JSONB))
    routing = sa.table('company_model_routing', sa.column('company_id', sa.String), sa.column('choices', JSONB), sa.column('revision', sa.Integer))
    members = sa.table('company_member', sa.column('id', sa.String), sa.column('reasoning_preference', JSONB), sa.column('reasoning_revision', sa.Integer))
    rows = db.execute(sa.select(services)).mappings().all()
    lookup = {(row['id'], model['id']): model for row in rows for model in row['models']}
    routings = db.execute(sa.select(routing)).mappings().all()
    assistants = {r['company_id']: r['choices'].get('assistant') for r in routings}
    for row in rows:
        choice = assistants.get(row['company_id'])
        converted = [direct_model(m, choice.get('presetId'), selection_supplied=True) if isinstance(choice, dict) and choice['serviceId'] == row['id'] and choice['modelId'] == m['id'] else direct_model(m) for m in row['models']]
        db.execute(services.update().where(services.c.id == row['id']).values(models=converted))
    for row in routings:
        db.execute(routing.update().where(routing.c.company_id == row['company_id']).values(choices=migrated_choices(row['choices'], lookup), revision=row['revision'] + 1))
    for row in db.execute(sa.select(members)).mappings().all():
        old = row['reasoning_preference']
        if old and 'presetId' in old:
            effort = legacy_reference_effort(old, lookup)
            direct = {k: old[k] for k in ('serviceId', 'modelId')} | {'effort': effort} if effort else None
            db.execute(members.update().where(members.c.id == row['id']).values(reasoning_preference=direct, reasoning_revision=row['reasoning_revision'] + 1))


def downgrade():
    # A data-format downgrade must not invent editable presets or lose exact
    # parameters. Keep the newer data readable by a subsequent re-upgrade.
    raise RuntimeError('直接思考强度配置不能降级为命名预设；请恢复迁移前数据库备份')
