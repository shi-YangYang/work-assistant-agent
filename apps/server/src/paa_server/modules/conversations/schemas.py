from paa_server.core.schemas import Input
from pydantic import Field, field_validator


class ConversationCreate(Input):
    title: str = Field(default='新会话', min_length=1, max_length=120)

    @field_validator('title')
    @classmethod
    def nonblank_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('请输入会话名称')
        return value


class ConversationEdit(ConversationCreate):
    expectedRevision: int = Field(ge=1)
