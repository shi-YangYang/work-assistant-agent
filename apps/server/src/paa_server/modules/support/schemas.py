from paa_server.core.schemas import Input
from pydantic import AwareDatetime, Field, model_validator
from typing import Literal
from uuid import UUID


class SupportDiagnostics(Input):
    occurredAt: AwareDatetime | None = None
    page: Literal[
        '/', '/login', '/assistant', '/assistant/:conversationId', '/messages/:id',
        '/work', '/work/:id', '/reports', '/reports/:id', '/team', '/team/details',
        '/team/reports', '/team/:id', '/members', '/settings/account',
        '/settings/appearance', '/settings/rules', '/settings/models',
        '/settings/usage', '/settings/support',
    ] | None = None
    category: Literal[
        'network', 'timeout', 'unauthorized', 'forbidden', 'rate_limited', 'server',
        'invalid_response', 'conflict', 'validation', 'cancelled', 'unknown',
    ] | None = None
    httpStatus: int | None = Field(default=None, ge=100, le=599, strict=True)
    requestId: UUID | None = None
    appVersion: str | None = Field(default=None, max_length=80, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._+\-]{0,79}$')
    browser: str | None = Field(default=None, max_length=80, pattern=r'^(Chrome|Safari|Firefox|Edge|Opera|Samsung Internet|WeChat|DingTalk|Unknown)( [0-9][0-9.]*)?$')
    os: str | None = Field(default=None, max_length=80, pattern=r'^(Windows|macOS|iOS|iPadOS|Android|Linux|Unknown)( [0-9][0-9._]*)?$')
    viewport: str | None = Field(default=None, max_length=11, pattern=r'^[1-9][0-9]{0,4}x[1-9][0-9]{0,4}$')


class FeedbackCreate(Input):
    description: str = Field(min_length=1, max_length=4000)
    diagnostics: SupportDiagnostics = Field(default_factory=SupportDiagnostics)

    @model_validator(mode='after')
    def nonempty(self):
        self.description = self.description.strip()
        if not self.description:
            raise ValueError('请填写问题描述')
        return self


class FeedbackPatch(Input):
    state: Literal['pending', 'resolved']
    handlingNote: str = Field(max_length=2000)
    expectedRevision: int = Field(ge=1, strict=True)
