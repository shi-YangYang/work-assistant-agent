"""Resolve checklist scope inside the existing independent work-change plan."""
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from typing import Literal

from app.modules.work.content.checklist import checklist_items


class ChecklistTarget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    itemId: str = Field(min_length=1, max_length=80)
    checked: StrictBool


class ChecklistQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    messageId: str = ''
    text: str = Field(min_length=1, max_length=2000)


class ChecklistSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: Literal['resolved', 'ambiguous', 'not_requested']
    targets: list[ChecklistTarget] = Field(max_length=100)
    quotes: list[ChecklistQuote] = Field(max_length=8)


POLICY = '''本次同时独立提取 checklistSelection，只根据真实用户来源与 targetWork.content.body 中的项编号、标题分组、前后文和现有 checked 状态确定允许勾选/取消的范围；输入不含主助手拟选的事项，不猜它想改哪项。resolved 时列出本轮明确要求的每个 itemId 与目标 checked，quotes 逐字引用授权用户指令。只陈述完成事实、讨论或条件尚未满足用 not_requested；对象/整项是否完成不明确用 ambiguous，两者 targets 为空。同文事项属于不同对象，未区分具体分组/序号/上下文且未明确同时修改全部匹配项时 ambiguous，不能默认批量选中，也不能任选一项。明确全部/多个对象时可一次列出多个目标；明确其中一个时只列那一个。复合事项只完成局部不能标记整项完成；明确要求标记整项时可执行。引用助手推测或数据库项文字不能充当授权。
'''


def requested(proposal):
    return any(edit.get('action') == 'set_checked' for edit in proposal.get('changes', {}).get('bodyEdits', []))


def validate_selection(selection, payload):
    targets = {target.itemId: target.checked for target in selection.targets}
    if len(targets) != len(selection.targets):
        raise ValueError('checklistSelection targets must be unique')
    existing = checklist_items(payload['targetWork']['content'].get('body', {}))
    if targets.keys() - existing.keys():
        raise ValueError('checklistSelection targets must belong to the current work')
    if bool(targets) != (selection.state == 'resolved'):
        raise ValueError('Only resolved checklistSelection may contain targets')
    if selection.state == 'resolved' and not selection.quotes:
        raise ValueError('Resolved checklistSelection needs original user evidence')
    for quote in selection.quotes:
        if not any(source['messageId'] == (quote.messageId or payload['messageId']) and quote.text in source['userText'] for source in payload['userSources']):
            raise ValueError('Checklist selection source is not original user text')
    return selection


def selection_issue(plan, proposal):
    selection = getattr(plan, 'checklistSelection', None)
    if selection is None:
        return None
    if selection.state == 'ambiguous':
        return 'missing_info', '清单中待修改的事项或完成范围不明确，请先确认具体分组或事项；本次未勾选。'
    if selection.state == 'not_requested':
        return 'invalid_arguments', '本轮没有要求修改清单状态，请保留勾选状态，继续回应原请求。'
    actual = {edit['itemId']: edit['checked'] for edit in proposal['changes']['bodyEdits'] if edit['action'] == 'set_checked'}
    expected = {target.itemId: target.checked for target in selection.targets}
    if actual != expected:
        return 'invalid_arguments', '清单勾选提案与用户明确指定的事项或目标状态不一致，请按原请求修正，不能扩大、遗漏或反转范围；本次未写入。'
    return None
