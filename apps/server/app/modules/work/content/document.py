"""Versioned, bounded editor documents; no HTML or executable URLs."""
import copy
import json
from uuid import uuid5, NAMESPACE_URL
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from app.core.schemas import Input

BLOCKS = {'paragraph', 'heading', 'bulletList', 'orderedList', 'taskList', 'blockquote', 'codeBlock', 'horizontalRule', 'material'}
NODES = BLOCKS | {'text', 'hardBreak', 'listItem', 'taskItem'}
MARKS = {'bold', 'italic', 'strike', 'code', 'link'}


def safe_link(value):
    return isinstance(value, str) and len(value) <= 2000 and urlsplit(value).scheme in ('http', 'https', 'mailto') and not any(ord(c) < 32 for c in value)


def validate_nodes(nodes):
    if not isinstance(nodes, list) or len(nodes) > 1000:
        raise ValueError('工作内容最多 1000 个内容块')
    nodes = copy.deepcopy(nodes)
    count, ids = 0, set()
    def check(node, depth=0):
        nonlocal count
        count += 1
        if count > 10000 or depth > 12 or not isinstance(node, dict) or set(node) - {'type', 'attrs', 'content', 'text', 'marks'} or node.get('type') not in NODES:
            raise ValueError('工作内容节点无效或过于复杂')
        kind = node['type']
        if not isinstance(node.get('content', []), list) or not isinstance(node.get('marks', []), list):
            raise ValueError('内容和文字格式必须为数组')
        if depth == 0 and kind not in BLOCKS:
            raise ValueError('工作内容需要段落或列表')
        attrs = node.setdefault('attrs', {})
        allowed = {'id'} | ({'level'} if kind == 'heading' else {'checked'} if kind == 'taskItem' else {'start'} if kind == 'orderedList' else {'language'} if kind == 'codeBlock' else {'materialId'} if kind == 'material' else set())
        if not isinstance(attrs, dict) or set(attrs) - allowed:
            raise ValueError('工作内容属性无效')
        if depth == 0 or kind == 'taskItem':
            identifier = attrs.get('id') or str(uuid5(NAMESPACE_URL, ('work-task:' if kind == 'taskItem' else 'work-block:') + str(len(ids)) + ':' + json.dumps(node, sort_keys=True, ensure_ascii=False)))
            if not isinstance(identifier, str) or len(identifier) > 80 or identifier in ids:
                raise ValueError('内容块编号无效或重复')
            attrs['id'] = identifier
            ids.add(identifier)
        if kind == 'heading' and attrs.get('level', 2) not in (1, 2, 3):
            raise ValueError('仅支持三级标题')
        if kind == 'taskItem':
            if not isinstance(attrs.get('checked', False), bool):
                raise ValueError('清单状态无效')
            attrs.setdefault('checked', False)
        if kind == 'material' and (not isinstance(attrs.get('materialId'), str) or not 1 <= len(attrs['materialId']) <= 80):
            raise ValueError('材料编号无效')
        if 'text' in node and (kind != 'text' or not isinstance(node['text'], str)):
            raise ValueError('文字节点无效')
        if kind == 'text' and 'text' not in node:
            raise ValueError('缺少文字')
        for mark in node.get('marks', []):
            if not isinstance(mark, dict) or set(mark) - {'type', 'attrs'} or mark.get('type') not in MARKS:
                raise ValueError('文字格式无效')
            if not isinstance(mark.get('attrs', {}), dict):
                raise ValueError('文字格式属性无效')
            if mark['type'] == 'link':
                if set(mark.get('attrs', {})) - {'href', 'target', 'rel', 'class'} or not safe_link(mark.get('attrs', {}).get('href')):
                    raise ValueError('链接只能使用 http、https 或 mailto')
                mark['attrs'] = {'href': mark['attrs']['href'], 'target': '_blank', 'rel': 'noopener noreferrer nofollow'}
            elif mark.get('attrs'):
                raise ValueError('文字格式属性无效')
        children = node.get('content', [])
        allowed_children = {'bulletList': {'listItem'}, 'orderedList': {'listItem'}, 'taskList': {'taskItem'}, 'paragraph': {'text', 'hardBreak'}, 'heading': {'text', 'hardBreak'}, 'codeBlock': {'text'}, 'text': set(), 'hardBreak': set(), 'horizontalRule': set(), 'material': set()}.get(kind, BLOCKS)
        for child in children:
            if not isinstance(child, dict) or child.get('type') not in allowed_children:
                raise ValueError('内容块嵌套无效')
            check(child, depth + 1)
    for node in nodes:
        check(node)
    if len(json.dumps(nodes, ensure_ascii=False).encode()) > 250000:
        raise ValueError('工作内容不能超过 250 KB')
    return nodes


class WorkDocument(Input):
    schemaVersion: int = Field(default=1, ge=1, le=1)
    content: list[dict] = Field(default_factory=list)
    _nodes = field_validator('content')(validate_nodes)


def plain_text(body):
    def walk(node):
        kind = node.get('type')
        if kind == 'hardBreak':
            return '\n'
        separator = '\n' if kind in ('taskList', 'bulletList', 'orderedList', 'taskItem', 'listItem', 'blockquote') else ''
        text = node.get('text', '') + separator.join(walk(c) for c in node.get('content', []))
        return ('☑ ' if node.get('attrs', {}).get('checked') else '☐ ') + text if kind == 'taskItem' else text
    return '\n'.join(walk(n) for n in (body or {}).get('content', []))


def material_ids(body):
    def walk(node):
        return ([node['attrs']['materialId']] if node.get('type') == 'material' else []) + [v for child in node.get('content', []) for v in walk(child)]
    return list(dict.fromkeys(v for n in (body or {}).get('content', []) for v in walk(n)))


def from_text(text):
    return WorkDocument(content=[{'type': 'paragraph', 'content': [{'type': 'text', 'text': line}]} if line else {'type': 'paragraph'} for line in text.split('\n')] if text else []).model_dump()


def edit_document(body, edits):
    from app.modules.work.content.checklist import checked_edits, checklist_block, checklist_items, reject_overlapping_targets
    nodes = copy.deepcopy(body.get('content', []))
    edits = checked_edits(edits)
    reject_overlapping_targets(nodes, edits)
    existing_items = checklist_items(body)
    for edit in edits:
        action = edit['action']
        if action == 'set_checked':
            if edit['itemId'] not in existing_items:
                raise ValueError('清单事项已变化，请重新读取工作正文')
            if edit.get('blockId'):
                target = next((node for node in body.get('content', []) if node.get('attrs', {}).get('id') == edit['blockId']), None)
                if target is None or target['type'] != 'taskList' or edit['itemId'] not in checklist_items({'content': [target]}):
                    raise ValueError('清单事项不属于指定清单，请重新读取工作正文')
            checklist_items({'content': nodes})[edit['itemId']]['attrs']['checked'] = edit['checked']
            continue
        if action == 'append_checklist' and edit.get('blockId'):
            target = next((node for node in nodes if node.get('attrs', {}).get('id') == edit['blockId']), None)
            if target is None or target['type'] != 'taskList':
                raise ValueError('目标清单已变化，请重新读取工作正文中的清单块')
            target.setdefault('content', []).extend(checklist_block(edit['items'])['content'])
            continue
        if action in ('append', 'append_checklist'):
            nodes.extend([checklist_block(edit['items'])] if action == 'append_checklist' else edit.get('blocks', []))
            continue
        index = next((i for i, n in enumerate(nodes) if n.get('attrs', {}).get('id') == edit['blockId']), None)
        if index is None:
            raise ValueError('内容块已变化，请重新读取工作正文')
        if action == 'replace_checklist' and checklist_items({'content': [nodes[index]]}):
            raise ValueError('已有清单请保留事项编号编辑；勾选请使用 set_checked')
        replacement = validate_nodes([checklist_block(edit['items'])] if action == 'replace_checklist' else edit.get('blocks', [])) if action != 'remove' else []
        if replacement:
            replacement[0].setdefault('attrs', {})['id'] = edit['blockId']
        nodes[index:index + 1] = replacement
    return WorkDocument(content=nodes).model_dump()
