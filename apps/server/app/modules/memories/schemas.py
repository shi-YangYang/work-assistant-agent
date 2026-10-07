from pydantic import Field
from app.core.schemas import Input
from .limits import MAX_CHARACTERS


class MemoryRevision(Input):
    expectedRevision: int = Field(ge=0)


class MemorySettings(MemoryRevision):
    enabled: bool


class MemoryDocument(MemoryRevision):
    markdown: str = Field(max_length=MAX_CHARACTERS)
