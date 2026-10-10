"""Phase names reflect orchestration boundaries, never inferred thoughts."""
from langchain_core.messages import HumanMessage, ToolMessage


def model_phase(messages, job_id, *, nested=False):
    latest = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
    if latest and latest.id in (f'delivery-repair:{job_id}', f'delivery-references:{job_id}', f'completion-repair:{job_id}'):
        return '完善答复'
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            if message.id in (f'delivery-repair:{job_id}', f'delivery-references:{job_id}', f'completion-repair:{job_id}'):
                return '完善答复'
            return '处理请求' if nested else '等待模型响应'
        if isinstance(message, ToolMessage):
            return '整理工具结果'
    return '处理请求'


async def model_activity(context, phase):
    """Publish only a phase and timestamp, once per transition, never reasoning."""
    from app.agent.runtime.budget import internal_call_kind
    from app.db.base import now
    from app.tasks.lease import lease
    from app.tasks.nodes.node_execution import active_node
    from app.tasks.nodes.node_state import execution, save
    active = active_node.get()
    if not context.node_retry or internal_call_kind.get() or not active or active[1] != 'model':
        return
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        state = execution(job)
        row = next((item for item in state.get('nodes', []) if item['id'] == active[0]), None)
        if row and row['state'] == 'running' and row.get('scope') == context.node_scope:
            row['activity'] = {'phase': phase, 'startedAt': now().isoformat()}
            save(job, state)
