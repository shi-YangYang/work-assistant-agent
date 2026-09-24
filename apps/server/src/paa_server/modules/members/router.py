from .commands import add_member_command, change_member_command, delete_member_command
from fastapi import APIRouter
from paa_server.core.errors import problem
from paa_server.http.dependencies import ADMIN, DB
from paa_server.modules.auth.sessions import passwords, revoke_member
from paa_server.modules.members.models import Member
from paa_server.modules.members.schemas import MemberCreate, MemberPatch, ResetPassword
from paa_server.modules.members.serializers import member_dto
from paa_server.modules.members.service import visible_member
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

router = APIRouter()


@router.get('/api/v1/members')
async def members(actor=ADMIN, db=DB):
    return {'items': [member_dto(m) for m in (await db.scalars(select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee', Member.deleted.is_(False)).order_by(Member.created_at))).all()]}


@router.post('/api/v1/members', status_code=201)
async def add_member(body: MemberCreate, actor=ADMIN, db=DB):
    return await add_member_command(body, actor, db)


@router.patch('/api/v1/members/{identifier}')
async def change_member(identifier: str, body: MemberPatch, actor=ADMIN, db=DB):
    return await change_member_command(identifier, body, actor, db)


@router.post('/api/v1/members/{identifier}/reset-password')
async def reset_password(identifier: str, body: ResetPassword, actor=ADMIN, db=DB):
    item = await visible_member(db, actor, identifier, employee_only=True)
    if item.deleted:
        problem(404, '账号已删除')
    item.password_hash = await run_in_threadpool(passwords.hash, body.password)
    await revoke_member(db, item.id)
    return {'ok': True}


@router.delete('/api/v1/members/{identifier}')
async def delete_member(identifier: str, actor=ADMIN, db=DB):
    return await delete_member_command(identifier, actor, db)
