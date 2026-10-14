"""Checklist identity and bounded edits within the existing work document."""
import copy
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field, StrictBool, TypeAdapter, field_validator
from app.core.schemas import Input


class ChecklistItem(Input):
    text: str = Field(min_length=1, max_length=12000)
    checked: StrictBool = False

    @field_validator('text')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('清单事项不能为空')
        return value


class AppendBlocks(Input):
    action: Literal['append']
    blocks: list[dict] = Field(default_factory=list, max_length=1000)


class ReplaceBlocks(Input):
    action: Literal['replace']
    blockId: str = Field(min_length=1, max_length=80)
    blocks: list[dict] = Field(default_factory=list, max_length=1000)


class RemoveBlock(Input):
    action: Literal['remove']
    blockId: str = Field(min_length=1, max_length=80)


class AppendChecklist(Input):
    action: Literal['append_checklist']
    items: list[ChecklistItem] = Field(min_length=1, max_length=1000)
    blockId: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator('blockId')
    @classmethod
    def supplied_target(cls, value):
        if value is None:
            raise ValueError('指定清单时需要实际内容块编号')
        return value


class ReplaceChecklist(AppendChecklist):
    action: Literal['replace_checklist']
    blockId: str = Field(min_length=1, max_length=80)


class SetChecked(Input):
    action: Literal['set_checked']
    itemId: str = Field(min_length=1, max_length=80)
    checked: StrictBool
    blockId: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator('blockId')
    @classmethod
    def supplied_target(cls, value):
        if value is None:
            raise ValueError('指定清单时需要实际内容块编号')
        return value


BodyEdit = Annotated[AppendBlocks | ReplaceBlocks | RemoveBlock | AppendChecklist | ReplaceChecklist | SetChecked, Field(discriminator='action')]
_edit_adapter = TypeAdapter(list[BodyEdit])


def checked_edits(edits):
    values = _edit_adapter.validate_python(edits)
    if len(values) > 100:
        raise ValueError('单次最多修改 100 个内容目标')
    targets = [getattr(value, 'itemId', getattr(value, 'blockId', None)) for value in values]
    targets = [target for target in targets if target is not None]
    if len(set(targets)) != len(targets):
        raise ValueError('同一内容目标不能重复修改')
    return [value.model_dump(exclude_unset=True) for value in values]


def compatible_body(body, namespace):
    """Assign deterministic legacy IDs on a copy, never mutate a stored snapshot."""
    result = copy.deepcopy(body)
    def visit(node, path):
        if node.get('type') == 'taskItem':
            attrs = node.setdefault('attrs', {})
            attrs.setdefault('id', str(uuid5(NAMESPACE_URL, f'work-item:{namespace}:{path}')))
            attrs.setdefault('checked', False)
        for index, child in enumerate(node.get('content', [])):
            visit(child, f'{path}/{index}')
    for index, node in enumerate(result.get('content', [])):
        visit(node, str(index))
    return result


def checklist_items(body):
    result = {}
    def visit(node):
        if node.get('type') == 'taskItem' and node.get('attrs', {}).get('id'):
            result[node['attrs']['id']] = node
        for child in node.get('content', []):
            visit(child)
    for node in body.get('content', []):
        visit(node)
    return result


def checklist_block(items):
    return {'type': 'taskList', 'content': [
        {'type': 'taskItem', 'attrs': {'checked': item.get('checked', False)},
         'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': item['text']}]}]}
        for item in items
    ]}


def reject_overlapping_targets(nodes, edits):
    """Block replace/remove and item toggles cannot target overlapping content."""
    affected = set()
    for edit in edits:
        if edit['action'] == 'set_checked':
            # An optional list constraint does not mutate the list itself;
            # other item toggles and appends to the same list remain disjoint.
            targets = {edit['itemId']}
        elif edit['action'] == 'append_checklist' and edit.get('blockId'):
            # Appending new items does not modify any existing item's state.
            targets = {edit['blockId']}
        elif edit.get('blockId'):
            block = next((node for node in nodes if node.get('attrs', {}).get('id') == edit['blockId']), None)
            targets = {edit['blockId']} | set(checklist_items({'content': [block]})) if block else {edit['blockId']}
        else:
            targets = set()
        if affected & targets:
            raise ValueError('正文修改范围重叠，请分清要修改的目标')
        affected |= targets


def assign_new_item_ids(body, previous):
    """Unrecognized identities are new items, including copied/deleted items.

    Runs only inside the write transaction after idempotency admission; request
    validation and repeated preview/read operations remain deterministic.
    """
    existing = checklist_items(previous)
    for identifier, item in checklist_items(body).items():
        if identifier not in existing:
            item['attrs']['id'] = str(uuid4())
    return body
