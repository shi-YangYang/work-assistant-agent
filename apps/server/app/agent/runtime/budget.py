"""Transient provider instructions; never part of graph or conversation state."""
from contextvars import ContextVar
from app.tasks.budget.service import current
from app.tasks.budget.state import policy

final_answer_call = ContextVar('budget_final_answer', default=False)


def instruction(context):
    state = current(context)
    if not state:
        return None
    limits = policy(state)
    phase = state['phase']
    note = (f"内部执行信息：还可调用工具 {max(0, limits.tools - state['tools'])} 次，"
            f"探索模型请求 {max(0, limits.models - limits.reserve_models - state['models'])} 次，"
            f"剩余 {int(state['remainingSeconds'])} 秒；阶段 {phase}。")
    if phase in ('finalizing', 'exhausted'):
        note += '直接交付已有结果并说明未完成范围，不再调用工具或重做业务。确有未完成项时首行用 <!--noria:{"remaining":["具体未完成项"]}-->（最多8项，每项240字以内，整个标记不超过1024字符）；已完成则仍用 <!--noria:{}-->。'
    elif phase == 'near_limit':
        note += '优先补齐关键依据，已有足够信息就回答，不必用完额度。'
    else:
        note += '信息足够就直接回答。'
    return note + '这些数字仅用于安排执行，不在用户答复中复述调用次数、时间限额、预留或内部停止原因。'


async def invoke(context, operation, *, timeout):
    import asyncio
    from app.tasks.budget.state import TaskBudgetStopped
    from app.tasks.budget.service import current
    try:
        return await asyncio.wait_for(operation, timeout=timeout)
    except asyncio.TimeoutError:
        state = current(context)
        if state and state['remainingSeconds'] <= 0:
            raise TaskBudgetStopped('time') from None
        raise
