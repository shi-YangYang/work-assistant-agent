from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Revision(Input):
    expectedRevision: int = Field(ge=1)
