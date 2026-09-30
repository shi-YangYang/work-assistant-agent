from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.messages.service import active_message
from app.security.access import require


async def check_sources(db, actor, sources):
    for ref in sources:
        if ref['kind'] == 'attachment':
            item = await db.get(Attachment, ref['id'])
            if not item or item.deleted or item.company_id != actor.company_id or item.sha256 != ref['sha256'] or item.extraction_revision != ref['revision']:
                problem(403, '生成文件的来源已变化或被删除')
            if item.owner_id == actor.id:
                parent = await active_message(db, item.message_id, actor)
                await require(db, actor, parent.access)
            else:
                from app.security.access import require as require_business
                await require_business(db, actor, ref['access'])
        else:
            problem(403, '文件来源无效')


def remember_sources(job, context, sources):
    previous = job.result.get('sandboxSources', [])
    retained = list({entry['id']: entry for entry in [*previous, *sources]}.values())
    job.result = {**job.result, 'sandboxSources': retained}
    context.document_versions.update({item['id']: item['revision'] for item in sources})


async def task_sources(db, actor, job, context, direct_sources):
    """Bind actual task reads even when generated code embeds their values."""
    versions = dict(context.document_versions)
    for value in job.result.get('documentReads', {}).values():
        versions[value[0]] = value[1]
    for identifier in context.image_sources:
        item = await db.get(Attachment, identifier)
        if item:
            versions[identifier] = item.extraction_revision
    sources = list(direct_sources)
    for identifier, revision in versions.items():
        item = await db.get(Attachment, identifier)
        if not item or item.deleted or item.extraction_revision != revision:
            problem(403, '生成文件的来源已变化或被删除')
        sources.append({'kind': 'attachment', 'id': item.id, 'sha256': item.sha256,
                        'revision': revision, 'access': job.access})
    remember_sources(job, context, sources)
    retained = job.result['sandboxSources']
    await check_sources(db, actor, retained)
    return retained
