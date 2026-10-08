"""Company-serialized, account-scoped reasoning preferences and sanitized views."""
from sqlalchemy import select
from app.core.digests import digest
from app.core.errors import problem
from app.modules.members.models import Company, Member
from app.modules.model_services.models import ModelRouting
from app.modules.model_services.service import get_service, validate_choice
from .policy import effective_selection


async def reasoning_state(db, actor):
    # Same ordering as model administration; freezes routing and revisions until commit.
    await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    member = await db.scalar(select(Member).where(Member.id == actor.id, Member.company_id == actor.company_id).with_for_update().execution_options(populate_existing=True))
    routing = await db.get(ModelRouting, actor.company_id)
    selection = routing.choices.get('assistant') if routing else None
    options, chosen, service = [], None, None
    if selection:
        service = await get_service(db, actor.company_id, selection['serviceId'])
        model = validate_choice(service.models, selection, 'assistant')
        chosen, options = effective_selection(selection, model, member.reasoning_preference)
    if member.reasoning_preference and (not options or not chosen or any(member.reasoning_preference.get(k) != chosen.get(k) for k in ('serviceId', 'modelId', 'effort'))):
        member.reasoning_preference = None
        member.reasoning_revision += 1
    config = digest({'company': actor.company_id, 'routing': routing.revision if routing else 0, 'service': service.id if service else None, 'revision': service.revision if service else 0})
    selected = next((p for p in options if p['effort'] == chosen.get('effort')), None) if chosen else None
    return member, chosen, {'options': options, 'selected': selected, 'preferenceRevision': member.reasoning_revision, 'configVersion': config}


async def read_settings(db, actor):
    return (await reasoning_state(db, actor))[2]


def require_current(view, reference):
    if reference.configVersion != view['configVersion'] or reference.preferenceRevision != view['preferenceRevision']:
        problem(409, '思考强度设置已变化，请同步后重新发送', 'reasoning_settings_changed')


async def update_settings(db, actor, body):
    member, selection, view = await reasoning_state(db, actor)
    require_current(view, body)
    if not selection or not any(p['effort'] == body.effort for p in view['options']):
        problem(422, '该思考强度未向当前账号开放')
    member.reasoning_preference = {key: selection[key] for key in ('serviceId', 'modelId')} | {'effort': body.effort}
    member.reasoning_revision += 1
    return {**view, 'selected': next(p for p in view['options'] if p['effort'] == body.effort), 'preferenceRevision': member.reasoning_revision}


async def validate_message_settings(db, actor, reference):
    _, selection, view = await reasoning_state(db, actor)
    if reference:
        from .legacy import LegacyReasoningReference
        if isinstance(reference, LegacyReasoningReference):
            problem(409, '思考强度配置已升级，请同步后重新发送', 'reasoning_settings_changed')
        require_current(view, reference)
        if reference.effort != (view['selected']['effort'] if view['selected'] else None):
            problem(409, '思考强度设置已变化，请同步后重新发送', 'reasoning_settings_changed')
    return selection
