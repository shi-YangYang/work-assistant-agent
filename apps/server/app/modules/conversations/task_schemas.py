"""Semantic task descriptions never replace database permissions or source checks."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskInterpretation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str = Field(default='', max_length=400)
    relation: Literal['new', 'continue'] = 'new'
    state: Literal['completed', 'needs_input', 'needs_confirmation', 'processing', 'blocked'] = 'completed'
    remaining: list[str] = Field(default_factory=list, max_length=8)
    directiveChange: Literal['keep', 'replace', 'clear'] = 'keep'
    directiveQuote: str = Field(default='', max_length=2000)
    directiveScope: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def coherent_state(self):
        if any(not item.strip() for item in self.remaining):
            raise ValueError('remaining must name concrete unfinished requirements')
        if self.state == 'completed' and self.remaining:
            raise ValueError('completed cannot contain remaining requirements; use needs_input or blocked as appropriate')
        if self.state == 'needs_input' and not self.remaining:
            raise ValueError('needs_input requires a concrete missing input; awaiting future messages is not an unfinished task')
        return self


class TaskSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    messageId: str
    revision: int
    digest: str
    quote: str
    kind: Literal['user_instruction'] = 'user_instruction'
    scope: str = ''
    targetId: str = ''
    fields: list[str] = Field(default_factory=list, max_length=6)
