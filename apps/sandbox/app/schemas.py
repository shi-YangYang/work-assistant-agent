"""Trusted control protocol; caller identities never reach generated code."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
import base64
import re

MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024


class InputFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=180)
    data: str = Field(max_length=MAX_INPUT_BYTES * 4 // 3 + 4)

    @field_validator('name')
    @classmethod
    def safe_name(cls, value):
        if value in ('.', '..') or any(c in value for c in '/\\\x00') or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid filename')
        return value

    def bytes(self):
        return base64.b64decode(self.data, validate=True)


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-f0-9]{64}$')
    owner: str = Field(pattern=r'^[a-f0-9]{64}$')
    code: str = Field(min_length=1, max_length=60000)
    inputs: list[InputFile] = Field(default_factory=list, max_length=12)

    def validate_inputs(self):
        if len({item.name for item in self.inputs}) != len(self.inputs):
            raise ValueError('Duplicate filenames')
        if sum(len(item.bytes()) for item in self.inputs) > MAX_INPUT_BYTES:
            raise ValueError('Input exceeds 40 MiB')


def execution_id(value):
    if not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Invalid execution ID')
    return value
