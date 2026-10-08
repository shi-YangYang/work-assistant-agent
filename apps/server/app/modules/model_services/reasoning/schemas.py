from pydantic import Field
from app.core.schemas import Input


class ReasoningReference(Input):
    effort: str | None = Field(default=None, max_length=32)
    preferenceRevision: int = Field(ge=0)
    configVersion: str = Field(min_length=1, max_length=128)


class UpdateReasoning(ReasoningReference):
    effort: str = Field(min_length=1, max_length=32)


