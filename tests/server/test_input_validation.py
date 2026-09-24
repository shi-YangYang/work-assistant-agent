import pytest
from datetime import date
from fastapi import HTTPException
from paa_server.core.input_rules import MEMBER_RULES, PASSWORD_RULES
from paa_server.core.periods import period_range
from paa_server.http.validation import validation_detail
from paa_server.modules.auth.schemas import Password
from paa_server.modules.conversations.schemas import ConversationEdit
from paa_server.modules.members.schemas import AdminBootstrap, MemberCreate, ResetPassword
from paa_server.modules.reports.periods import period
from paa_server.modules.work.schemas import DraftEdit, Progress
from pydantic import ValidationError
from types import SimpleNamespace


def test_every_new_password_entry_uses_shared_limits():
    for model, field, other in (
        (MemberCreate, 'password', {'username': '111', 'name': '1'}),
        (AdminBootstrap, 'password', {'username': 'admin', 'name': '管理员'}),
        (ResetPassword, 'password', {}),
        (Password, 'newPassword', {}),
    ):
        schema = model.model_json_schema()['properties'][field]
        assert schema['minLength'] == PASSWORD_RULES['min'] == 4
        assert schema['maxLength'] == PASSWORD_RULES['max'] == 128
        for size in (4, 128):
            model(**other, **{field: 'x' * size})
        for size in (3, 129):
            with pytest.raises(ValidationError):
                model(**other, **{field: 'x' * size})
    member = MemberCreate.model_json_schema()['properties']
    assert member['username']['pattern'] == MEMBER_RULES['username']['pattern']
    assert member['name']['maxLength'] == MEMBER_RULES['name']['max']


@pytest.mark.parametrize('model,field,extra', [
    (Progress, 'title', {}),
    (DraftEdit, 'title', {'expectedRevision': 1}),
    (ConversationEdit, 'title', {'expectedRevision': 1}),
    (MemberCreate, 'name', {'username': '111', 'password': '1111'}),
])
def test_visible_names_are_normalized_and_never_blank(model, field, extra):
    with pytest.raises(ValidationError) as raised:
        model(**extra, **{field: ' \t\n '})
    detail = validation_detail(raised.value.errors())
    assert field in detail['fieldErrors']
    assert getattr(model(**extra, **{field: '  正常内容  '}), field) == '正常内容'


def test_nested_errors_keep_positions_and_do_not_echo_secrets():
    detail = validation_detail([
        {'loc': ('body', 'models', 0, 'language'), 'type': 'string_pattern_mismatch', 'input': 'secret-input'},
        {'loc': ('body', 'daily'), 'type': 'value_error', 'ctx': {'error': ValueError('截止时间不得早于生成时间')}, 'input': {'secret': 'never-echo'}},
        {'loc': ('body', 'apiKey'), 'type': 'value_error', 'ctx': {'error': ValueError('错误 https://private.example/token')}},
    ])
    assert detail['fieldErrors']['models.0.language'] == '识别语言格式不正确'
    assert detail['fieldErrors']['daily'] == '截止时间不得早于生成时间'
    assert not any(value in str(detail) for value in ('secret-input', 'never-echo', 'private.example'))


def test_extreme_dates_report_validation_errors_instead_of_overflow():
    company = SimpleNamespace(rules={'timezone': 'Asia/Shanghai'})
    with pytest.raises(HTTPException) as invalid_range:
        period_range(company, 'custom', date.max, date.max)
    assert invalid_range.value.status_code == 422
    for kind in ('daily', 'weekly'):
        with pytest.raises(HTTPException) as invalid_report:
            period(kind, date.max)
        assert invalid_report.value.status_code == 422
    assert period('daily', date(2026, 9, 22)) == (date(2026, 9, 22), date(2026, 9, 22))
    assert period('weekly', date(2026, 9, 22)) == (date(2026, 9, 21), date(2026, 9, 27))
