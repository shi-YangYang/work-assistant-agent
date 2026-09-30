"""Trusted control protocol; caller identities never reach generated code."""
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import base64
import re
import json
from typing import Literal

MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_ARGUMENT_BYTES = 240 * 1024
MAX_REQUEST_BYTES = (MAX_INPUT_BYTES + 2) // 3 * 4 + MAX_ARGUMENT_BYTES + 128 * 1024


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


class BuiltinTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['builtin']
    name: Literal['inspect_table', 'export_table', 'create_chart', 'create_document', 'create_slides']
    version: Literal[1]
    arguments: dict

    @field_validator('version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Version must be an integer')
        return value

    @model_validator(mode='after')
    def bounds(self):
        if type(self.version) is not int or len(json.dumps(self.arguments, ensure_ascii=False, allow_nan=False).encode()) > MAX_ARGUMENT_BYTES:
            raise ValueError('Unsupported version or arguments exceed 240 KiB')
        return self


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-f0-9]{64}$')
    owner: str = Field(pattern=r'^[a-f0-9]{64}$')
    code: str | None = Field(default=None, min_length=1, max_length=60000)
    inputs: list[InputFile] = Field(default_factory=list, max_length=12)

    task: BuiltinTask | None = None

    @model_validator(mode='after')
    def task_kind(self):
        if (self.code is None) == (self.task is None):
            raise ValueError('Provide exactly one of code or task')
        return self

    def serialized(self):
        # Original Python wire shape/order is also the durable receipt fingerprint.
        if self.task is not None:
            return json.dumps(self.model_dump(mode='json', exclude_none=True), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return self.model_dump_json(exclude_none=True)

    def validate_inputs(self):
        if len({item.name for item in self.inputs}) != len(self.inputs):
            raise ValueError('Duplicate filenames')
        if sum(len(item.bytes()) for item in self.inputs) > MAX_INPUT_BYTES:
            raise ValueError('Input exceeds 40 MiB')


def execution_id(value):
    if not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Invalid execution ID')
    return value
