"""Read-only compatibility for length metadata in historical completions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


class AnswerLength(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote: str = Field(min_length=1, max_length=160)
    unit: Literal['cjk_characters', 'words']
    exclude_title: bool = False

    body: SkipJsonSchema[str | None] = Field(default=None, min_length=1)
