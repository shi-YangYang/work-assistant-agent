from app.core.input_rules import MEMBER_RULES, PASSWORD_RULES
from app.core.schemas import Input
from pydantic import Field


class Login(Input):
    username: str = Field(min_length=1, max_length=MEMBER_RULES['username']['max'])
    password: str = Field(min_length=1, max_length=PASSWORD_RULES['max'])


class Password(Input):
    currentPassword: str = Field(default='', max_length=PASSWORD_RULES['max'])
    useDingTalk: bool = False
    newPassword: str = Field(min_length=PASSWORD_RULES['min'], max_length=PASSWORD_RULES['max'])
