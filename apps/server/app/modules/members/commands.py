from fastapi import HTTPException
from app.core.errors import problem
from app.modules.auth.sessions import passwords, revoke_member
from app.modules.members.models import Company, Member
from app.modules.members.serializers import member_dto
from app.modules.members.service import visible_member
from app.modules.reports.scheduling.schedule import eligibility_changed as reporting_eligibility_changed
from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool


async def add_member_command(body, actor, db):
    if body.role != 'employee':
        problem(403, '成员管理仅可添加员工')
    if await db.scalar(select(Member.id).where(Member.username == body.username.lower())):
        raise HTTPException(409, detail={'code': 'username_taken', 'message': '账号名称已被使用', 'fieldErrors': {'username': '账号名称已被使用'}})
    item = Member(company_id=actor.company_id, username=body.username.lower(), name=body.name, role=body.role, password_hash=await run_in_threadpool(passwords.hash, body.password))
    db.add(item)
    await db.flush()
    await reporting_eligibility_changed(db, item)
    return member_dto(item)


async def change_member_command(identifier, body, actor, db):
    await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    item = await visible_member(db, actor, identifier, employee_only=True)
    if item.deleted:
        problem(404, '账号已删除')
    item.active = body.active
    await reporting_eligibility_changed(db, item)
    if not item.active:
        await revoke_member(db, item.id)
    return member_dto(item)


async def delete_member_command(identifier, actor, db):
    await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    item = await visible_member(db, actor, identifier)
    if item.role != 'employee':
        problem(404, '成员不存在或无权查看')
    # Preserve the owner ID for history, but release both login identities.
    # The colon is outside the allowed username alphabet, so this reserved
    # tombstone cannot conflict with an account created through the API.
    if not item.deleted:
        from app.modules.interactions.lifecycle import expire
        await expire(db, owner_id=item.id)
        from app.modules.conversations.models import ConversationContext, ConversationTaskState
        await db.execute(delete(ConversationTaskState).where(ConversationTaskState.owner_id == item.id, ConversationTaskState.company_id == actor.company_id))
        await db.execute(delete(ConversationContext).where(ConversationContext.owner_id == item.id, ConversationContext.company_id == actor.company_id))
        item.active, item.deleted, item.password_hash = False, True, None
        item.username = 'deleted:' + item.id
        await reporting_eligibility_changed(db, item)
        await revoke_member(db, item.id)
        from app.modules.auth.models import DingTalkIdentity
        await db.execute(delete(DingTalkIdentity).where(DingTalkIdentity.member_id == item.id, DingTalkIdentity.company_id == actor.company_id))
    from app.modules.voiceprints.cleanup import remove_enrollment
    from app.modules.voiceprints.models import Voiceprint
    enrollment = await db.scalar(select(Voiceprint).where(Voiceprint.member_id == item.id, Voiceprint.company_id == actor.company_id).with_for_update())
    await remove_enrollment(db, enrollment)
    return {'ok': True}
