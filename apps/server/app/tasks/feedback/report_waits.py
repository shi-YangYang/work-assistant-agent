"""Delegate receipt-owned report progress to its real asynchronous operation."""
import re
from datetime import date, timedelta


# A small grammar of status clauses, not an open-ended keyword classifier. Every
# clause must be consumed: an extra request, submission or missing input stays.
WAIT_STATUS = re.compile(
    r'(?:的)?(?:草稿)?(?:的)?(?:生成任务|生成)?(?:仍然|仍|还|尚)?'
    r'(?:正在|在)?(?:服务器)?(?:排队)?(?:生成)?'
    r'(?:处理中|生成中|排队中|等待生成|正在生成)'
)
UNCONFIRMED_SAVE = re.compile(
    r'(?:暂未|尚未|还未|未)(?:能)?'
    r'(?:(?:拿到|收到|取得)(?:保存)?回执|确认(?:已)?保存(?:完成)?)'
)
RESULT_LOCATION = re.compile(r'稍后可在[“「\'"《]?我的报告[”」\'"》]?查看(?:结果)?')
REPORT_RESULT = re.compile(r'(?:的)?(?:草稿)?后(?:告知|告诉)(?:用户|我)(?:保存)?结果')


def wait_clause(text):
    parts = re.split(r'[，,；;]', text.rstrip('。.!！'))
    if not WAIT_STATUS.fullmatch(parts[0]):
        return False
    if len(parts) > 1 and UNCONFIRMED_SAVE.fullmatch(parts[1]):
        parts.pop(1)
    return len(parts) == 1 or len(parts) == 2 and bool(RESULT_LOCATION.fullmatch(parts[1]))


def request_day(clock):
    # This clock is authored by the server, in the company's timezone. Never
    # infer relative periods from today's read time or a model-supplied date.
    match = re.match(r'当前请求时间：(\d{4}-\d{2}-\d{2})T', clock)
    try:
        return date.fromisoformat(match[1]) if match else None
    except ValueError:
        return None


def owned_reports(job, cards):
    """Use the existing authorized operation and child binding, never prose."""
    items = {item['id']: item for item in job.result.get('taskItems', [])}
    reports = []
    for card in cards:
        item = items.get(card.get('taskItemId'), {})
        operation = item.get('attemptedOperation', {})
        title = re.fullmatch(r'(\d{4}-\d{2}-\d{2}) (日报|周报)', card.get('title', ''))
        child = card.get('job') or {}
        if (card.get('action') != 'generate_report' or card.get('state') not in ('running', 'succeeded')
                or card.get('messageId') != getattr(job, 'target_id', None)
                or item.get('receiptId') != card.get('id') or operation.get('action') != 'generate_report'
                or operation.get('submitAfter') is not False or not title or not card.get('objectId')
                or child.get('kind') != 'report' or child.get('targetId') != card['objectId']):
            continue
        kind = 'daily' if title[2] == '日报' else 'weekly'
        try:
            period = date.fromisoformat(operation.get('date', ''))
        except (ValueError, TypeError):
            continue
        if kind == 'weekly':
            period -= timedelta(days=period.weekday())
        if operation.get('kind') != kind or period.isoformat() != title[1]:
            continue
        reports.append((card, item, period, title[2]))
    return reports


def completion_wait(card, *, submit_after=False):
    """Advertise the optional completion contract only for queued report tools."""
    if (not submit_after and card.get('action') == 'generate_report' and card.get('state') == 'running'
            and card.get('id') and (card.get('job') or {}).get('kind') == 'report'):
        return {'completionWait': {'waitingOperationIds': [card['id']]},
                'completionNote': '报告交给后台生成，结束本轮即可。最终 noria 标记使用 completionWait；生成等待不写入 remaining，其他真实未完成项照常保留。'}
    return {}


def invalid_waiting_ids(job, cards, identifiers):
    # A model reference only delegates status to an already authorized child.
    # It never removes prose requirements or changes the card/child state.
    known = {card['id'] for card, item, _, _ in owned_reports(job, cards)
             if (item.get('userSource') or {}).get('messageId') == getattr(job, 'target_id', None)}
    return set(identifiers) - known


def report_aliases(job, cards, day):
    aliases = {}
    reports = owned_reports(job, cards)
    for card, item, period, kind in reports:
        title = card['title']
        names = [title, title.replace(' ', ''), f'《{title}》']
        if day:
            current = day if kind == '日报' else day - timedelta(days=day.weekday())
            if period == current:
                names.extend(('今天日报', '今日日报') if kind == '日报' else ('本周周报', '这周周报'))
        source = item.get('userSource') or {}
        # An unqualified "周报" can only refer to an exact period already stated
        # by this request and authorized in this item. Multiple receipts remain
        # ambiguous, including two periods or two drafts of the same period.
        if (sum(report[3] == kind for report in reports) == 1
                and source.get('messageId') == getattr(job, 'target_id', None)
                and any(name in source.get('userText', '') for name in names)):
            names.append(kind)
        for name in names:
            aliases.setdefault(name, set()).add(card['id'])
    return aliases


def normalize(job, cards, task, *, clock=''):
    """A bound report card owns progress, including the eventual result notice.

    No report is marked successful here: queued, running, failed and cancelled
    children are still derived from the real card. Unknown prose is retained.
    """
    remaining = task.get('remaining', [])
    if not remaining or task.get('state') not in ('blocked', 'needs_input', 'needs_confirmation', 'processing'):
        return task
    protected = set(job.result.get('nodeExecution', {}).get('budgetBlockedTools', []))
    protected.update(row.get('message', '') for row in job.result.get('toolOutcomes', [])
                     if row.get('category') not in ('success', 'processing', 'confirmation'))
    aliases = report_aliases(job, cards, request_day(clock))

    def bound_status(text, *, result_only=False):
        text = text.rstrip('。.!！')
        matches = set()
        for name, identifiers in aliases.items():
            if not result_only and text.startswith(name) and wait_clause(text[len(name):].strip()):
                matches.update(identifiers)
            for action in ('保存', '生成并保存', '创建并保存'):
                prefix = action + name
                if text.startswith(prefix) and REPORT_RESULT.fullmatch(text[len(prefix):]):
                    matches.update(identifiers)
        return len(matches) == 1

    for name in ('intentTaskInterpretation', 'explicitTaskContext'):
        source = job.result.get(name) or {}
        for text in source.get('remaining', []):
            # Authorization often lists "save this draft, then report back" as
            # a pending step. Once its authorized child exists, the existing
            # public receipt will report the result. A needs_input/blocked
            # authorization, or any other requirement, remains protected.
            if source.get('state') not in ('needs_confirmation', 'processing') or not bound_status(text, result_only=True):
                protected.add(text)
    retained = [text for text in remaining if text in protected or not bound_status(text)]
    if retained == remaining:
        return task
    return {**task, 'state': task['state'] if retained else 'completed', 'remaining': retained}
