from app.core.personas import DEFAULT_PERSONA, PersonaId
from app.core.schemas import Input
from pydantic import Field, field_validator, model_validator


def nonblank_title(value):
    if value is None or not value.strip():
        raise ValueError('请输入会话名称')
    return value.strip()


class ConversationCreate(Input):
    title: str = Field(default='新会话', min_length=1, max_length=120)
    personaId: PersonaId = DEFAULT_PERSONA

    _title = field_validator('title')(nonblank_title)


class ConversationEdit(Input):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    personaId: PersonaId | None = None
    expectedRevision: int = Field(ge=1)

    _title = field_validator('title')(nonblank_title)

    @model_validator(mode='after')
    def changes_present(self):
        if not self.model_fields_set & {'title', 'personaId'}:
            raise ValueError('请提供会话名称或人设')
        if 'personaId' in self.model_fields_set and self.personaId is None:
            raise ValueError('请选择有效人设')
        return self
