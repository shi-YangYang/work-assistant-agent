"""Add persistent work bodies, progress entries and work-owned materials."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import json
from uuid import uuid5, NAMESPACE_URL

revision = '0025_work_records'
down_revision = '0024_account_execution_mode'
branch_labels = depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('company_id', sa.String(36), sa.ForeignKey('company.id'), nullable=False), sa.Column('owner_id', sa.String(36), sa.ForeignKey('company_member.id'), nullable=False)]


def upgrade():
    op.create_table('company_work_update', *common(), sa.Column('work_id', sa.String(36), sa.ForeignKey('company_work_item.id'), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('text', sa.String(12000), nullable=False), sa.Column('material_ids', postgresql.JSONB(), nullable=False), sa.Column('origin', sa.String(24), nullable=False), sa.Column('deleted', sa.Boolean(), nullable=False), sa.Column('work_revision', sa.Integer(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('company_work_update_revision', *common(), sa.Column('update_id', sa.String(36), sa.ForeignKey('company_work_update.id'), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('text', sa.String(12000), nullable=False), sa.Column('material_ids', postgresql.JSONB(), nullable=False), sa.Column('origin', sa.String(24), nullable=False), sa.Column('deleted', sa.Boolean(), nullable=False), sa.Column('work_revision', sa.Integer(), nullable=False), sa.UniqueConstraint('update_id', 'revision'))
    op.create_table('company_work_material', *common(), sa.Column('work_id', sa.String(36), sa.ForeignKey('company_work_item.id'), nullable=False), sa.Column('attachment_id', sa.String(36), sa.ForeignKey('company_attachment.id'), nullable=False), sa.Column('source', postgresql.JSONB(), nullable=False), sa.Column('removed', sa.Boolean(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False))
    for table, keys in [('company_work_update', ['company_id', 'owner_id', 'work_id']), ('company_work_update_revision', ['company_id', 'owner_id', 'update_id']), ('company_work_material', ['company_id', 'owner_id', 'work_id', 'attachment_id'])]:
        for key in keys:
            op.create_index('ix_' + table + '_' + key, table, [key])
    connection = op.get_bind()
    # Preserve original text, dates and IDs. Never manufacture today's progress.
    for table in ('company_work_item', 'company_work_revision'):
        for row in connection.execute(sa.text(f'SELECT id, content FROM {table}')).mappings():
            content = dict(row['content'])
            summary = content.get('summary', '')
            body = {'schemaVersion': 1, 'content': [{'type': 'paragraph', 'attrs': {'id': str(uuid5(NAMESPACE_URL, row['id'] + ':' + str(i)))}, **({'content': [{'type': 'text', 'text': line}]} if line else {})} for i, line in enumerate(summary.split('\n'))] if summary else []}
            content.update(body=body, bodyText=summary, materialIds=[])
            connection.execute(sa.text(f'UPDATE {table} SET content=CAST(:content AS jsonb) WHERE id=:id'), {'id': row['id'], 'content': json.dumps(content, ensure_ascii=False)})
    last = {}
    for row in connection.execute(sa.text('SELECT * FROM company_work_revision ORDER BY work_id, revision')).mappings():
        summary = row['content'].get('summary', '')
        if not summary.strip() or last.get(row['work_id']) == summary:
            continue
        last[row['work_id']] = summary
        identifier = str(uuid5(NAMESPACE_URL, 'work-update:' + row['id']))
        values = {'id': identifier, 'company': row['company_id'], 'owner': row['owner_id'], 'work': row['work_id'], 'text': summary, 'origin': row['origin'], 'stamp': row['created_at'], 'revision': row['revision']}
        connection.execute(sa.text("INSERT INTO company_work_update (id,company_id,owner_id,work_id,text,origin,created_at,updated_at,revision,work_revision,material_ids,deleted) VALUES (:id,:company,:owner,:work,:text,:origin,:stamp,:stamp,1,:revision,'[]',false)"), values)
        connection.execute(sa.text("INSERT INTO company_work_update_revision (id,company_id,owner_id,update_id,text,origin,created_at,revision,work_revision,material_ids,deleted) VALUES (:rid,:company,:owner,:id,:text,:origin,:stamp,1,:revision,'[]',false)"), {**values, 'rid': str(uuid5(NAMESPACE_URL, 'work-update-revision:' + row['id']))})


def downgrade():
    for table in ('company_work_material', 'company_work_update_revision', 'company_work_update'):
        op.drop_table(table)
    for table in ('company_work_item', 'company_work_revision'):
        op.execute(f"UPDATE {table} SET content=content - 'body' - 'bodyText' - 'materialIds'")
