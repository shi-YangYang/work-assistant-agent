"""Public business feedback is distinct from private repair diagnostics."""
import re

DIAGNOSTIC_MARKERS = ('变更计划不匹配', '服务端没放行', '服务端这次还是没放行', '服务端未放行',
                      '内部前置', '授权校验器', '独立授权核对', 'Schema 校验失败')
DIAGNOSTIC_FIELDS = re.compile(
    r'\b(?:proposedOperation|requiredFields|appendFields|targetContent|deliverableSelection)\b|'
    r'(?:failureKind|denialScope)\s*[:=：]\s*[a-z_]+|'
    r'\b(?:existingOperation|report_kind|report_date|source_tokens)\b|'
    r'(?:修正|补齐|填写|传入|重试)[^。！？\n]{0,50}\b(?:changes|bodyEdits|requiredFields)\b|'
    r'\bchanges\.(?:body|materials|materialIds)\b|'
    r'系统(?:判定|校验|核对)[^。！？\n]{0,100}(?:拦下|拦截|不允许|未授权|没放行)|'
    r'(?:materials|materialIds|body|bodyEdits|changes)\s*(?:[:=：]\s*)?'
    r'(?:未要求修改|未被授权|被保留|preserve)'
)


def diagnostic(text):
    return any(marker in text for marker in DIAGNOSTIC_MARKERS) or bool(DIAGNOSTIC_FIELDS.search(text))


def technical_question(text):
    # Terms in attached code/logs need not be repeated in the user's question.
    return bool(re.search(r'(代码|字段|Schema|日志|接口|报错).*(解释|意思|含义|分析)|'
                          r'(解释|分析|看一下|说明).*(代码|字段|Schema|日志|接口|报错)', text, re.I))


def user_gap(value):
    recovery = value.get('recovery') or {}
    missing = recovery.get('missingInputs')
    return (recovery.get('owner') == 'user' and isinstance(missing, list) and bool(missing)
            and all(isinstance(item, dict) and item.get('field') in ('target', 'materials', 'content', 'decision')
                    and isinstance(item.get('question'), str) and item['question'].strip()
                    and isinstance(item.get('unavailableFromSources'), str) and item['unavailableFromSources'].strip()
                    for item in missing))


def message(value):
    if value.get('publicMessage'):
        return value['publicMessage']
    recovery = value.get('recovery') or {}
    if user_gap(value):
        return '；'.join(item['question'] for item in recovery['missingInputs'])
    category = value.get('category', '')
    fallback = value.get('message') or '这项操作尚未完成。'
    internal = bool(value.get('diagnostic')) or diagnostic(fallback)
    if internal:
        fallback = '这项操作暂未完成，已保存的内容会保留。'
    elif value.get('message') and category not in ('missing_info', 'invalid_arguments'):
        return fallback
    return {
        'permission_denied': '你目前没有权限完成这项操作。',
        'conflict': '内容已发生变化，这项操作尚未完成。',
        'invalid_arguments': '这项操作暂未完成，已保存的内容会保留。',
        'transient_failure': '暂时无法完成这项操作，请稍后重试。',
        'missing_info': '这项操作暂未完成，已保存的内容会保留。',
        'not_requested': '本次未执行这项操作。',
    }.get(category, fallback)


def error(text):
    """Project controlled error slots, preserving useful ordinary business errors."""
    return message({'message': text}) if diagnostic(text) else text


def node_error(row):
    """Known internal failures are identified by producer metadata, not prose."""
    text = row.get('error', '')
    if text and (row.get('errorCode') == 'child_failed' or (
            row.get('kind') == 'authorization' and row.get('errorCode') == 'invalid_response')):
        return '这一步暂未完成，请稍后重试；已保存的内容会保留。'
    return error(text)


def job_error(job, text=None):
    text = job.error if text is None else text
    state = job.result.get('nodeExecution', {})
    for row in state.get('nodes', []):
        if row.get('scope') == state.get('scope') and row.get('error') == text:
            projected = node_error(row)
            if projected != text:
                return projected
    return error(text)


def outcome(value, job):
    """Old structured diagnostics get the same projection as new tool results."""
    failures = [item for item in job.result.get('toolOutcomes', [])
                if item.get('category') in ('missing_info', 'invalid_arguments', 'conflict', 'permission_denied', 'transient_failure')]
    replacements = {item.get('message'): message(item) for item in failures if item.get('message')}
    def safe(text):
        return replacements.get(text, job_error(job, text))
    result = {**value, 'reason': safe(value.get('reason', '')),
              'remaining': list(dict.fromkeys(safe(text) for text in value.get('remaining', [])))}
    if (failures and not any(user_gap(item) for item in failures)
            and not job.result.get('waitingInteractionId') and value.get('nextAction') == 'reply'):
        result.update(state='partial' if value.get('completed') else 'blocked', nextAction='none')
    return result


def feedback(values, outcomes=()):
    evidence = {item['key']: item for item in outcomes if item.get('key')}
    return [{**{key: value[key] for key in ('key', 'step', 'action', 'label', 'state') if key in value},
             'message': message({**evidence.get(value.get('key'), {}), **value})} for value in values]


def model_result(value):
    """Keep repair instructions machine-readable; never relay the judge's prose."""
    if not isinstance(value, dict) or not value.get('recovery'):
        return value
    fields = [{key: item[key] for key in ('field', 'code') if key in item}
              for item in value.get('fieldIssues', [])]
    return {key: item for key, item in {**value, 'message': message(value), 'fieldIssues': fields}.items()
            if key not in ('diagnostic', 'publicMessage')}


def prose(text, job, user_text, *, complete=True):
    """Filter only unsolicited diagnostics for failures in this task.

    A failed operation buffers a sentence, not the entire answer, so a diagnostic
    split across network chunks cannot leak then disappear. Normal answers and
    user-supplied technical terms keep their original streaming behavior.
    """
    failures = [item for item in job.result.get('toolOutcomes', [])
                if item.get('category') in ('invalid_arguments', 'missing_info', 'conflict', 'permission_denied')]
    if not failures or technical_question(user_text):
        return text
    parts = re.findall(r'[^。！？\n]*(?:[。！？\n]|$)', text)
    if parts and parts[-1] == '':
        parts.pop()
    diagnostics = {sentence.strip() for failure in failures
                   for raw in (failure.get('diagnostic', ''), failure.get('message', ''))
                   if diagnostic(raw)
                   for sentence in re.findall(r'[^。！？\n]+', raw) if sentence.strip()}
    result = []
    for index, part in enumerate(parts):
        finished = part.endswith(('。', '！', '？', '\n'))
        if not complete and index == len(parts) - 1 and not finished:
            break
        # Bare source-code names and ordinary technical prose are not errors.
        # Only known diagnostic syntax absent from the user's question is removed.
        fields = DIAGNOSTIC_FIELDS.search(part)
        internal = any(marker in part and marker not in user_text for marker in DIAGNOSTIC_MARKERS)
        internal = internal or bool(fields and fields.group() not in user_text)
        internal = internal or any(sentence in part and sentence not in user_text for sentence in diagnostics)
        if internal:
            replacement = message(failures[-1])
            if not result or replacement not in result[-1]:
                result.append(replacement + '\n')
        else:
            result.append(part)
    return ''.join(result)
