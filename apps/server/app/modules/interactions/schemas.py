from typing import Literal
from app.core.schemas import Input
from pydantic import Field, model_validator


class QuestionOption(Input):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=300)
    objectType: Literal['work', 'report', 'member'] | None = None
    objectId: str | None = None


class Question(Input):
    id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=400)
    type: Literal['single', 'multiple', 'text'] = 'text'
    options: list[QuestionOption] = Field(default_factory=list, max_length=12)
    allowCustom: bool = True

    @model_validator(mode='after')
    def valid_options(self):
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError('问题选项重复')
        if self.type != 'text' and not self.options:
            raise ValueError('选择题需要真实候选项')
        return self


class Answer(Input):
    questionId: str = Field(min_length=1, max_length=80)
    optionIds: list[str] = Field(default_factory=list, max_length=12)
    text: str = Field(default='', max_length=2000)


class AnswerRequest(Input):
    expectedRevision: int = Field(ge=1)
    answers: list[Answer] = Field(min_length=1, max_length=3)
