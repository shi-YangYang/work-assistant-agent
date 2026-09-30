"""Bounded display metadata; never reads business records or model reasoning."""
import json
import re
import unicodedata
from urllib.parse import urlsplit

LABELS = {
    'inspect_table': '检查表格', 'export_table': '导出表格',
    'create_chart': '生成图表', 'create_document': '生成文档', 'create_slides': '生成幻灯片',
    'run_python': '运行代码', 'request_user_input': '等待用户回答', 'finish_task': '整理答复',
    'find_work_items': '查找工作', 'get_work_item': '读取工作',
    'get_message_context': '读取消息', 'get_business_actions': '读取操作结果',
    'query_reports': '查找报告', 'query_report_obligations': '查找汇报待办',
    'find_documents': '查找文件', 'read_document': '读取文件', 'read_file': '读取材料',
    'find_team_members': '查找成员', 'query_team_business': '查询团队工作',
    'read_team_source': '读取团队来源', 'propose_progress': '整理进展建议',
    'propose_followup': '整理督办建议', 'save_deliverable': '整理成果',
    'read_deliverable': '读取成果', 'read_execution': '读取执行记录',
    'web_search': '搜索资料', 'web_fetch': '读取网页', 'execute_business_action': '执行业务操作',
}
ACTIONS = {'create_work': '创建工作', 'update_work': '更新工作', 'delete_work': '删除工作',
           'generate_report': '报告生成入队', 'edit_report': '修改报告',
           'submit_report': '提交报告', 'delete_report': '删除报告'}
INTERNAL = frozenset({'get_business_actions', 'read_execution', 'finish_task', 'request_user_input'})
TITLE_INPUTS = frozenset({'run_python', 'propose_progress', 'propose_followup', 'save_deliverable'})
FILE_OUTPUTS = frozenset({'export_table', 'create_chart', 'create_document', 'create_slides'})
READ_TITLES = frozenset({'get_work_item', 'read_deliverable', 'read_team_source', 'read_execution'})
STATUS_NAMES = {'in_progress': '进行中', 'blocked': '有阻碍', 'done': '已完成'}


def hostname(value):
    if not isinstance(value, str):
        return ''
    try:
        parsed = urlsplit(value)
        return parsed.hostname or '' if parsed.scheme in ('http', 'https') else ''
    except ValueError:
        return ''


def text(value, *, filename=False):
    if not isinstance(value, str):
        return ''
    value = ''.join(char for char in value[:1000] if not unicodedata.category(char).startswith('C'))
    if filename:
        if value.startswith(('https://', 'http://')):
            return text(hostname(value))
        value = value.replace('\\', '/').rsplit('/', 1)[-1].split('?', 1)[0].split('#', 1)[0]
    value = re.sub(r'https?://[^\s<>]+', lambda match: hostname(match.group()), value)
    value = re.sub(r'(?<!\S)(?:[A-Za-z]:[\\/]|/)[^\s<>]+', '', value)
    value = re.sub(r'\b(?:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|[0-9a-f]{24,})\b', '', value, flags=re.I)
    value = ' '.join(value.split()).strip()
    return value[:59] + '…' if len(value) > 60 else value


def mapping(value):
    return value if isinstance(value, dict) else {}


def choice(values, key, fallback=''):
    return values.get(key, fallback) if isinstance(key, str) else fallback


def report_subject(args):
    kind = choice({'daily': '日报', 'weekly': '周报'}, args.get('kind', args.get('report_kind', 'daily')), '报告')
    period = args.get('period', args.get('report_date', ''))
    return kind + (' · ' + period if isinstance(period, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', period) else '')


def tool_presentation(name, arguments, result=None):
    """Only named display fields from actual arguments / authorized tool results."""
    args = mapping(arguments)
    label, subject = LABELS.get(name, '执行操作'), ''
    if name in ('find_work_items', 'find_documents', 'find_team_members', 'web_search'):
        subject = args.get('query', '')
        if name == 'find_work_items' and not subject:
            subject = '我的工作' + (' · ' + choice(STATUS_NAMES, args.get('status')) if choice(STATUS_NAMES, args.get('status')) else '')
    elif name == 'web_fetch':
        subject = hostname(args.get('url'))
    elif name in TITLE_INPUTS:
        subject = args.get('title', '')
    elif name in FILE_OUTPUTS:
        subject = text(args.get('filename', ''), filename=True) or args.get('title', '')
    elif name in ('query_reports', 'query_report_obligations'):
        subject = report_subject(args)
    elif name == 'query_team_business':
        label = '查询团队报告' if args.get('kind') == 'report' else label
        subject = ' · '.join(text(args.get(key)) for key in ('employee_name', 'query') if text(args.get(key)))
    elif name == 'execute_business_action':
        label = choice(ACTIONS, args.get('action'), label)
        if args.get('action') == 'create_work':
            subject = mapping(args.get('changes')).get('title', '')
        elif args.get('action') == 'generate_report':
            subject = report_subject(args)
    if result is not None:
        try:
            value = mapping(json.loads(result.content))
        except (ValueError, TypeError, AttributeError):
            value = {}
        # Refusal/error payloads are not a source of authorized object metadata.
        usable = (getattr(result, 'status', '') != 'error' and 'error' not in value
                  and value.get('state') not in ('failed', 'unavailable', 'conflict', 'not_found', 'cancelled')
                  and value.get('category') != 'permission_denied')
        if usable:
            if name in READ_TITLES or name in ('web_fetch', 'execute_business_action'):
                subject = value.get('title') or mapping(value.get('preview')).get('title') or subject
            elif name == 'inspect_table':
                files = value.get('inputFiles')
                if isinstance(files, list) and len(files) == 1:
                    subject = text(files[0], filename=True)
            elif name == 'read_document':
                subject = text(mapping(value.get('attachment')).get('name'), filename=True)
            elif name in FILE_OUTPUTS:
                files = mapping(value.get('delivery')).get('files')
                if isinstance(files, list) and len(files) == 1:
                    subject = text(mapping(files[0]).get('name'), filename=True) or subject
    presentation = {'type': 'activity' if name in INTERNAL else 'operation'}
    if cleaned := text(subject):
        presentation['subject'] = cleaned
    return label, presentation
