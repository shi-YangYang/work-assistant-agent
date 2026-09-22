"""User-facing validation details, without echoing submitted values or secrets."""
import re


LABELS = {
    'username': '账号', 'password': '密码', 'currentPassword': '当前密码', 'newPassword': '新密码',
    'name': '名称', 'title': '标题', 'summary': '进展说明', 'blocker': '阻碍', 'nextStep': '下一步',
    'text': '文字内容', 'completed': '已完成工作', 'ongoing': '进行中工作', 'blockers': '阻碍',
    'next': '后续计划', 'baseUrl': 'API 地址', 'apiKey': 'API Key', 'model': '模型 ID',
    'language': '识别语言', 'corpId': '企业 CorpId', 'clientId': 'AppKey', 'secret': 'AppSecret',
    'description': '问题描述', 'handlingNote': '处理说明', 'q': '搜索内容', 'date': '日期',
    'start': '开始日期', 'end': '结束日期', 'dueDate': '截止日期', 'days': '汇报日期',
    'beforeMinutes': '提前提醒分钟数', 'timezone': '公司时区',
}


def validation_detail(errors):
    fields, field_errors, messages = [], {}, []
    for error in errors:
        location = error.get('loc', ())
        fields.append('.'.join(map(str, location)))
        path = location[1:] if location and location[0] in ('body', 'query', 'path') else location
        field = '.'.join(map(str, path))
        label = LABELS.get(str(path[-1]), '此项') if path else '输入内容'
        kind, context = error.get('type'), error.get('ctx', {})
        if kind == 'value_error':
            custom = str(context.get('error', ''))
            message = custom if (
                0 < len(custom) <= 220 and re.search(r'[\u3400-\u9fff]', custom)
                and not re.search(r'[<>\r\n]|https?://|traceback|authorization|bearer|sk-[a-z0-9]', custom, re.I)
            ) else f'{label}不符合要求'
        elif kind == 'missing':
            message = f'请填写{label}'
        elif kind == 'string_too_short':
            message = f"{label}至少需要 {context['min_length']} 个字符"
        elif kind == 'string_too_long':
            message = f"{label}最多允许 {context['max_length']} 个字符"
        elif kind == 'string_pattern_mismatch':
            message = f'{label}格式不正确'
        elif kind in ('int_parsing', 'int_from_float', 'int_type'):
            message = f'{label}请输入整数'
        elif kind in ('greater_than_equal', 'less_than_equal'):
            message = f"{label}{'不能小于' if kind == 'greater_than_equal' else '不能大于'} {context['ge' if kind == 'greater_than_equal' else 'le']}"
        elif kind in ('too_long', 'too_short'):
            message = f"{label}{'最多' if kind == 'too_long' else '至少'}需要 {context['max_length' if kind == 'too_long' else 'min_length']} 项"
        elif kind.startswith('date_') or kind.startswith('time_'):
            message = f'{label}无效，请重新选择'
        elif kind in ('literal_error', 'enum'):
            message = f'{label}请选择有效选项'
        else:
            message = f'{label}格式不正确'
        if field:
            field_errors.setdefault(field, message)
        if message not in messages:
            messages.append(message)
    return {'code': 'validation_error', 'message': messages[0] if messages else '请检查输入内容', 'fields': fields, 'fieldErrors': field_errors}
