from datetime import date
from app.core.schemas import Input, Revision
from pydantic import Field, field_validator, model_validator
from typing import Literal


class Progress(Input):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default='', max_length=4000)
    dueDate: date | None = None
    status: Literal['in_progress', 'blocked', 'done'] = 'in_progress'
    blocker: str = Field(default='', max_length=2000)
    nextStep: str = Field(default='', max_length=2000)

    @field_validator('title')
    @classmethod
    def nonblank_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('请输入工作标题')
        return value


class DraftEdit(Progress):
    expectedRevision: int = Field(ge=1)
    workId: str | None = None


class ConfirmItem(Revision):
    id: str


class Confirm(Input):
    items: list[ConfirmItem] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def distinct(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('进展重复')
        return self


class WorkEdit(Progress, Revision):
    sourceIds: list[str] = Field(default_factory=list, max_length=20)
