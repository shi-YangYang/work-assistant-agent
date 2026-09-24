from app.core.input_rules import MEMBER_RULES, PASSWORD_RULES
from app.core.schemas import Input
from pydantic import Field, field_validator
from typing import Literal


class MemberCreate(Input):
    username: str = Field(pattern=MEMBER_RULES['username']['pattern'])
    name: str = Field(min_length=MEMBER_RULES['name']['min'], max_length=MEMBER_RULES['name']['max'])
    role: Literal['admin', 'employee'] = 'employee'
    password: str = Field(min_length=PASSWORD_RULES['min'], max_length=PASSWORD_RULES['max'])

    @field_validator('name')
    @classmethod
    def nonblank_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('请输入姓名')
        return value


class AdminBootstrap(MemberCreate):
    role: Literal['admin'] = 'admin'


class MemberPatch(Input):
    active: bool


class ResetPassword(Input):
    password: str = Field(min_length=PASSWORD_RULES['min'], max_length=PASSWORD_RULES['max'])


def member_validation_errors(errors, *, reset=False):
    messages = {
        'name': f"姓名需为 {MEMBER_RULES['name']['min']}–{MEMBER_RULES['name']['max']} 个字符",
        'username': f"账号需为 {MEMBER_RULES['username']['min']}–{MEMBER_RULES['username']['max']} 位，仅支持字母、数字和 . _ @ -",
        'password': f"密码需为 {PASSWORD_RULES['min']}–{PASSWORD_RULES['max']} 位",
    }
    return {
        error['loc'][1]: messages[error['loc'][1]]
        for error in errors
        if len(error['loc']) == 2 and error['loc'][0] == 'body'
        and error['loc'][1] in messages
    }
