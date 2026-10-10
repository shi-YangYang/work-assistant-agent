from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from app.modules.memories.document import annotations_after, patch, injection, validate, forget_fragment


def test_patch_preserves_manual_markdown_and_moved_provenance():
    doc = annotations_after({}, '# 自定义标题\n\n第一段 **人工** 内容。\n\n- 第二段\n- 原顺序\n', 'manual')
    changed = patch(doc, '第二段', '新段落', explicit=True, source='current')
    assert changed['markdown'] == doc['markdown'].replace('第二段', '新段落')
    with pytest.raises(HTTPException, match='409'):
        patch(changed, '人工', '模型猜测', explicit=False, source='current')
    moved = annotations_after(doc, '- 第二段\n- 原顺序\n\n# 自定义标题\n\n第一段 **人工** 内容。\n', 'manual')
    assert all(row['origin'] == 'manual' for row in moved['annotations'])
    # Unrelated durable self-disclosure is still allowed after manual editing.
    appended = patch(doc, '', '最近在推进一个新项目。', explicit=False, source='current')
    assert appended['markdown'].startswith(doc['markdown'])


def test_unique_patch_dedup_capacity_and_credentials():
    doc = annotations_after({}, '同一内容\n\n同一内容', 'inferred')
    with pytest.raises(HTTPException):
        patch(doc, '同一内容', '替换', explicit=True, source='current')
    assert patch(doc, '', '同一内容', explicit=False, source='current') == doc
    for value in ('x' * 6001, '密码：abc123456', 'sk-' + 'abcdef' * 8):
        with pytest.raises(HTTPException):
            validate(value)


@pytest.mark.parametrize(('existing', 'incoming'), [
    ('喜欢吃米饭。', '- 喜欢吃米饭。'),
    ('- 喜欢吃米饭。', '喜欢吃米饭。'),
    ('* 喜欢睡觉。', '1. 喜欢睡觉。'),
    ('- 喜欢吃米饭。\n- 喜欢睡觉。', '- 喜欢睡觉。'),
])
def test_append_ignores_list_format_without_new_annotations(existing, incoming):
    document = annotations_after({}, existing, 'manual')
    assert patch(document, '', incoming, explicit=False, source='current') == document


@pytest.mark.parametrize(('existing', 'incoming'), [
    ('不喜欢吃米饭。', '喜欢吃米饭。'),
    ('同事喜欢吃米饭。', '喜欢吃米饭。'),
    ('此项目先给结论。', '先给结论。'),
    ('# 以前\n\n- 喜欢吃米饭。\n\n# 现在\n\n喜欢面食。', '- 喜欢吃米饭。'),
    ('```text\n喜欢吃米饭。\n```', '喜欢吃米饭。'),
    ('    喜欢吃米饭。', '喜欢吃米饭。'),
    ('- 工作偏好\n  - 先给结论', '- 工作偏好\n- 先给结论'),
])
def test_append_does_not_deduplicate_substrings_or_different_scope(existing, incoming):
    document = annotations_after({}, existing, 'manual')
    changed = patch(document, '', incoming, explicit=False, source='current')
    assert changed['markdown'] == existing + '\n\n' + incoming
    assert changed['annotations'][0] == document['annotations'][0]


def test_append_expired_fact_does_not_hide_new_durable_fact():
    document = patch({'markdown': '', 'annotations': []}, '', '- 负责上线。',
                     explicit=False, source='old', expires='2020-01-01T00:00:00+00:00')
    changed = patch(document, '', '负责上线。', explicit=False, source='current')
    assert changed != document
    assert injection(changed, 200).strip() == '负责上线。'


def test_injection_preserves_heading_scope_whole_lists_and_expiration():
    doc = annotations_after({}, '# 此项目\n\n- 人工偏好一\n- 人工偏好二\n', 'manual')
    doc = patch(doc, '', '临时目标', explicit=False, source='current', expires='2020-01-01T00:00:00+00:00')
    value = injection(doc, 200, clock=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert '# 此项目' in value and '人工偏好二' in value and '临时目标' not in value
    assert injection(doc, 8) == ''
    with pytest.raises(HTTPException):
        patch(doc, '人工偏好一', '短期', explicit=True, source='current', expires='2030-01-01T00:00:00+00:00')


def test_disabled_forget_keeps_unrelated_facts_in_same_paragraph():
    markdown = '我负责运营，我喜欢简洁。\n\n别的段落保持原样。'
    assert forget_fragment('我负责运营。我喜欢简洁。', '我负责运营。') == '我负责运营。'
    fragment = forget_fragment(markdown, '我负责运营')
    assert markdown.replace(fragment, '') == '我喜欢简洁。\n\n别的段落保持原样。'
    with pytest.raises(HTTPException):
        forget_fragment('运营一。运营二。', '运营')


def test_manual_save_preserves_distinct_expiry_and_source_on_noop_and_move():
    empty = {'schemaVersion': 1, 'markdown': '', 'annotations': []}
    document = patch(empty, '', '临时负责上线。偏好简洁。', explicit=False,
                     source='temporary', expires='2027-01-01T00:00:00+00:00')
    document = patch(document, '偏好简洁。', '偏好详细。', explicit=True, source='preference')
    clock = datetime(2028, 1, 1, tzinfo=timezone.utc)
    unchanged = annotations_after(document, document['markdown'], 'manual')
    assert unchanged['annotations'] == document['annotations']
    assert injection(unchanged, 200, clock=clock).strip() == '偏好详细。'

    moved = annotations_after(document, '# 约定\n\n偏好详细。临时负责上线。', 'manual')
    spans = {moved['markdown'][row['start']:row['end']]: row for row in moved['annotations']}
    assert spans['临时负责上线。']['sourceMessage'] == 'temporary'
    assert spans['临时负责上线。']['expiresAt'] == '2027-01-01T00:00:00+00:00'
    assert spans['偏好详细。']['sourceMessage'] == 'preference'
    assert spans['偏好详细。']['origin'] == 'explicit'
    assert '临时负责上线' not in injection(moved, 200, clock=clock)
    assert '偏好详细。' in injection(moved, 200, clock=clock)


def test_manual_edit_marks_whole_changed_annotation_and_keeps_its_neighbor():
    empty = {'schemaVersion': 1, 'markdown': '', 'annotations': []}
    document = patch(empty, '', '临时负责上线。我喜欢黑色。', explicit=False,
                     source='temporary', expires='2027-01-01T00:00:00+00:00')
    changed = annotations_after(document, '临时负责上线。我喜欢蓝色。', 'manual')
    assert injection(changed, 200, clock=datetime(2028, 1, 1, tzinfo=timezone.utc)) == changed['markdown']
    assert all(row['origin'] == 'manual' and 'expiresAt' not in row for row in changed['annotations'])

    # Independent annotations in the same paragraph must not share that reset.
    document = patch(document, '我喜欢黑色。', '我喜欢黑色。', explicit=True, source='preference')
    changed = annotations_after(document, '临时负责上线。我喜欢蓝色。', 'manual')
    clock = datetime(2028, 1, 1, tzinfo=timezone.utc)
    assert injection(changed, 200, clock=clock).strip() == '我喜欢蓝色。'
    assert changed['annotations'][0]['expiresAt'] == '2027-01-01T00:00:00+00:00'
    assert changed['annotations'][1]['origin'] == 'manual'


@pytest.mark.parametrize(('markdown', 'target', 'remaining'), [
    ('I own Alpha. I prefer concise answers.', 'I own Alpha', 'I prefer concise answers.'),
    ('我负责飞鹭615。\n\n我喜欢简洁的回答。', '我负责飞鹭615', '我喜欢简洁的回答。'),
    ('第一条。\n\n我负责飞鹭615。\n\n最后一条。', '我负责飞鹭615', '第一条。\n\n最后一条。'),
    ('我喜欢简洁。\n\n我负责飞鹭615。', '我负责飞鹭615。', '我喜欢简洁。'),
    ('- 我负责飞鹭615。\n- 我喜欢简洁。', '我负责飞鹭615', '- 我喜欢简洁。'),
    ('1. 我负责飞鹭615。\n2. 我喜欢简洁。', '我负责飞鹭615', '2. 我喜欢简洁。'),
])
def test_forget_removes_only_complete_fact_with_adjacent_formatting(markdown, target, remaining):
    fragment = forget_fragment(markdown, target)
    assert markdown.replace(fragment, '', 1) == remaining


@pytest.mark.parametrize(('markdown', 'target'), [
    ('I own Alpha. I prefer concise answers.', 'Alpha'),
    ('我负责A和B两个项目。', 'A'),
    ('我负责A和B两个项目。', '我负责A'),
    ('我负责运营，我喜欢简洁。', '负责运营'),
])
def test_incomplete_forget_target_requests_clarity_without_expanding(markdown, target):
    with pytest.raises(HTTPException) as error:
        forget_fragment(markdown, target)
    assert error.value.status_code == 409
    assert '未删除任何内容' in error.value.detail['message']


def test_partial_list_replacement_does_not_repeat_surrounding_syntax():
    from app.modules.memories.document import patch
    document = {'markdown': '- 喜欢米饭。\n- 保留这一项。', 'annotations': []}
    result = patch(document, '喜欢米饭', '- 喜欢面条。', explicit=True, source='m')
    assert result['markdown'] == '- 喜欢面条。\n- 保留这一项。'
    assert document['markdown'] == '- 喜欢米饭。\n- 保留这一项。'
    code = {'markdown': '```text\n- 原片段。\n```', 'annotations': []}
    assert patch(code, '原片段', '- 新片段。', explicit=True, source='m')['markdown'] == '```text\n- - 新片段。。\n```'


def test_fact_under_another_heading_is_not_a_duplicate_of_unscoped_new_fact():
    from app.modules.memories.document import patch
    document = {'markdown': '# 同事\n\n- 喜欢米饭。', 'annotations': []}
    result = patch(document, '', '喜欢米饭。', explicit=False, source='m')
    assert result['markdown'].count('喜欢米饭。') == 2


@pytest.mark.parametrize('markdown', ['```text\n~~~\n- 片段。\n~~~\n```', '    - 片段。'])
def test_fragment_patch_keeps_literal_code_syntax(markdown):
    document = {'markdown': markdown, 'annotations': []}
    assert patch(document, '片段', '- 新片段。', explicit=True, source='m')['markdown'] == markdown.replace('片段', '- 新片段。')


def test_nested_list_fragment_preserves_parent_and_indentation():
    document = {'markdown': '- 饮食\n  - 喜欢米饭。\n  - 喜欢面条。', 'annotations': []}
    assert patch(document, '喜欢米饭', '- 喜欢粥。', explicit=True, source='m')['markdown'] == '- 饮食\n  - 喜欢粥。\n  - 喜欢面条。'
