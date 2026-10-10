"""Mutations require the caller's existing job lease/row lock transaction."""
import copy
import time
from contextvars import ContextVar
from . import policy as policies
from .state import create, snapshot, reserve

active_tool = ContextVar("budget_admitted_tool", default=False)


def ensure(job, context, *, instant=None):
    if job.kind != 'message':
        return None
    instant = time.time() if instant is None else instant
    state = job.result.get('taskBudget')
    if not state or state['round'] != job.attempt:
        previous = job.result.get('nodeExecution', {})
        legacy = previous if previous.get('deadline') and not state else None
        state = create(job.attempt, instant, legacy=legacy, configured=policies.DEFAULT)
        job.result = {**job.result, 'taskBudget': state}
    bind(context, state)
    return copy.deepcopy(state)


def bind(context, state):
    context.task_budget = copy.deepcopy(state)
    context.node_deadline = state['deadlineAt']
    context.calls, context.tools = state['models'], state['tools']


def consume(job, context, kind, *, identity=None, final_answer=False, instant=None):
    state = ensure(job, context, instant=instant)
    if state is None:
        return None
    value = reserve(state, kind, time.time() if instant is None else instant,
                    identity=identity, final_answer=final_answer, admitted_tool=active_tool.get())
    job.result = {**job.result, 'taskBudget': value}
    bind(context, value)
    return value


def finish(job, *, instant=None):
    state = job.result.get('taskBudget')
    if state and state['endedAt'] is None:
        state = snapshot(state, time.time() if instant is None else instant)
        state.pop('remainingSeconds')
        state.update(endedAt=time.time() if instant is None else instant, phase='ended')
        job.result = {**job.result, 'taskBudget': state}


def remaining(context):
    return max(.01, context.node_deadline - time.time())


def current(context):
    return snapshot(context.task_budget, time.time()) if context.task_budget else None


def reset(job):
    # Keep business receipts; only the explicit user-retry path clears budget.
    job.result = {key: value for key, value in job.result.items() if key != 'taskBudget'}


def finalize(job, context, reason):
    value = ensure(job, context)
    if value and value['phase'] not in ('exhausted', 'ended'):
        value.update(phase='finalizing', reason=reason)
        job.result = {**job.result, 'taskBudget': value}
        bind(context, value)
