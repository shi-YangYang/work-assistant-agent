"""Account-wide assistant preferences; business authorization remains separate."""
from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select
from app.core.errors import problem
from app.core.schemas import Input
from app.http.dependencies import AUTH, DB
from app.modules.operations.policy.execution_policy import ExecutionMode
from app.tasks.models import Job

router = APIRouter()


class ExecutionSettingsEdit(Input):
    executionMode: ExecutionMode
    fullAccessConfirmed: bool = False
    expectedRevision: int = Field(ge=1)


def execution_settings_dto(actor):
    return {'executionMode': actor.execution_mode, 'fullAccessConfirmed': actor.full_access_confirmed, 'modeRevision': actor.mode_revision}


@router.get('/api/v1/assistant/execution-settings')
async def execution_settings(actor=AUTH):
    return execution_settings_dto(actor)


@router.patch('/api/v1/assistant/execution-settings')
async def update_execution_settings(body: ExecutionSettingsEdit, actor=AUTH, db=DB):
    # AUTH holds the same company write lock as message admission and worker writes.
    if actor.mode_revision != body.expectedRevision:
        problem(409, '执行权限已在其他页面更新，请读取最新设置后再选择', 'execution_settings_changed')
    if body.executionMode == actor.execution_mode:
        return execution_settings_dto(actor)
    if await db.scalar(select(Job.id).where(Job.owner_id == actor.id, Job.company_id == actor.company_id, Job.kind == 'message', Job.state.in_(('queued', 'running'))).limit(1)):
        problem(409, '你有会话仍在处理中，请先中断或等待完成后再修改执行权限', 'assistant_busy')
    if body.executionMode == 'full' and not actor.full_access_confirmed and not body.fullAccessConfirmed:
        problem(422, '请先确认自主执行适用于此账号的所有会话')
    actor.full_access_confirmed = actor.full_access_confirmed or (body.executionMode == 'full' and body.fullAccessConfirmed)
    actor.execution_mode = body.executionMode
    actor.mode_revision += 1
    return execution_settings_dto(actor)
