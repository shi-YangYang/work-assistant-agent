from datetime import date, time
from app.core.schemas import Input, Revision
from pydantic import Field, model_validator
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    reminders: bool = True
    beforeMinutes: int = Field(default=30, ge=0, le=1440)

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
