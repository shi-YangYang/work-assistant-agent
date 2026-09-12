from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Input):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class Password(Input):
    currentPassword: str = Field(min_length=1, max_length=128)
    newPassword: str = Field(min_length=12, max_length=128)


class MemberCreate(Input):
    username: str = Field(pattern=r'^[a-zA-Z0-9._@-]{3,80}$')
    name: str = Field(min_length=1, max_length=80)
    role: Literal['admin', 'employee'] = 'employee'
    password: str = Field(min_length=12, max_length=128)


class MemberPatch(Input):
    active: bool


class ResetPassword(Input):
    password: str = Field(min_length=12, max_length=128)


class SendMessage(Input):
    text: str = Field(default='', max_length=8000)
    attachmentIds: list[str] = Field(default_factory=list, max_length=4)
    replyTo: str | None = None

    @model_validator(mode='after')
    def content_present(self):
        self.text = self.text.strip()
        if not self.text and not self.attachmentIds:
            raise ValueError('请输入文字或添加图片、语音')
        if len(set(self.attachmentIds)) != len(self.attachmentIds):
            raise ValueError('附件重复')
        return self


class TranscriptEdit(Input):
    text: str = Field(max_length=8000)
    expectedRevision: int = Field(ge=0)


class Progress(Input):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    status: Literal['in_progress', 'blocked', 'done'] = 'in_progress'
    blocker: str = Field(default='', max_length=2000)
    nextStep: str = Field(default='', max_length=2000)


class DraftEdit(Progress):
    expectedRevision: int = Field(ge=1)
    workId: str | None = None


class Revision(Input):
    expectedRevision: int = Field(ge=1)


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


class ReportContent(Input):
    completed: str = Field(default='', max_length=8000)
    ongoing: str = Field(default='', max_length=8000)
    blockers: str = Field(default='', max_length=8000)
    next: str = Field(default='', max_length=8000)


class ReportEdit(Revision):
    content: ReportContent


class GenerateReport(Input):
    kind: Literal['daily', 'weekly']
    date: date


class Schedule(Input):
    enabled: bool = False
    days: list[int] = Field(default_factory=list, max_length=7)
    generateTime: str = ''
    deadline: str = ''

    @model_validator(mode='after')
    def valid_schedule(self):
        if len(set(self.days)) != len(self.days) or any(d < 0 or d > 6 for d in self.days):
            raise ValueError('请选择有效日期')
        if self.enabled or self.generateTime or self.deadline:
            try:
                start, end = time.fromisoformat(self.generateTime), time.fromisoformat(self.deadline)
            except ValueError as error:
                raise ValueError('请完整设置生成及截止时间') from error
            if start.tzinfo or end.tzinfo or len(self.generateTime) != 5 or len(self.deadline) != 5 or end < start:
                raise ValueError('截止时间不得早于生成时间')
        if self.enabled and not self.days:
            raise ValueError('请选择汇报日期')
        return self


class Rules(Input):
    timezone: str = Field(max_length=80)
    daily: Schedule
    weekly: Schedule
    expectedRevision: int = Field(ge=1)

    @model_validator(mode='after')
    def valid_timezone(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError('公司时区无效') from error
        if self.weekly.enabled and len(self.weekly.days) != 1:
            raise ValueError('周报请选择一个生成日')
        return self
