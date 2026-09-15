"""Bounded configuration inputs shared by management and execution."""
import json
import math
import re
from typing import Literal
from pydantic import Field, model_validator
from .schemas import Input

PROTECTED = set('model messages stream stream_options tools tool_choice functions function_call response_format n store api_key apikey authorization headers extra_headers base_url baseurl url endpoint method body extra_body extra_query query input prompt user __proto__ prototype constructor max_tokens max_completion_tokens max_output_tokens timeout max_retries stop logprobs top_logprobs'.split())


def parameters(value):
    count = 0
    def walk(item, depth=0):
        nonlocal count
        if depth > 5:
            raise ValueError('推理参数嵌套不能超过 5 层')
        if isinstance(item, dict):
            for key, child in item.items():
                count += 1
                if count > 64 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key) or key.lower() in PROTECTED:
                    raise ValueError('推理参数包含受保护字段或过多字段')
                walk(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 32:
                raise ValueError('推理参数数组过长')
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str):
            if len(item) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in item) or re.search(r'\$\{|\{\{|<%|javascript:', item, re.I):
                raise ValueError('推理参数不支持模板或代码')
        elif isinstance(item, (float, int)) and not isinstance(item, bool):
            if not math.isfinite(item) or abs(item) > 1e12:
                raise ValueError('推理参数数值无效')
        elif item is not None and not isinstance(item, bool):
            raise ValueError('推理参数不是合法 JSON')
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False).encode()) > 4096:
        raise ValueError('推理参数必须是 4 KiB 以内的 JSON 对象')
    walk(value)
    return value


class Preset(Input):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    mode: Literal['simple', 'advanced'] = 'simple'
    value: str = Field(default='', max_length=512)
    parameters: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid(self):
        if self.mode == 'simple' and not self.value.strip():
            raise ValueError('请输入推理强度')
        parameters({'reasoning_effort': self.value} if self.mode == 'simple' else self.parameters)
        return self


class ServiceModel(Input):
    id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    protocol: Literal['chat', 'transcriptions', 'qwen-asr'] = 'chat'
    presets: list[Preset] = Field(default_factory=list, max_length=16)
    selectedPresetId: str | None = None
    streaming: bool = True
    language: str = Field(default='', pattern=r'^[a-zA-Z-]{0,20}$')

    @model_validator(mode='after')
    def valid(self):
        if any(ord(c) < 32 for c in self.model) or not self.model.strip():
            raise ValueError('模型 ID 无效')
        ids = [p.id for p in self.presets]
        if len(set(ids)) != len(ids) or (self.selectedPresetId is not None and self.selectedPresetId not in ids):
            raise ValueError('推理预设不存在或重复')
        if self.protocol != 'chat' and (self.presets or self.selectedPresetId):
            raise ValueError('语音接口不接受聊天推理预设')
        return self


class ServiceInput(Input):
    name: str = Field(min_length=1, max_length=80)
    baseUrl: str = Field(min_length=1, max_length=2048)
    apiKey: str = Field(default='', max_length=4096, repr=False)
    models: list[ServiceModel] = Field(default_factory=list, max_length=32)
    expectedRevision: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def valid(self):
        self.name = self.name.strip()
        if not self.name or (self.apiKey and not self.apiKey.strip()):
            raise ValueError('请输入有效名称或密钥')
        if any(ord(c) < 32 or ord(c) == 127 for c in self.apiKey):
            raise ValueError('密钥含无效字符')
        if len({m.id for m in self.models}) != len(self.models) or len({(m.model, m.protocol) for m in self.models}) != len(self.models):
            raise ValueError('模型配置重复')
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > 49152:
            raise ValueError('单服务配置不能超过 48 KiB')
        return self


class ConfigRequest(ServiceInput):
    serviceId: str | None = None
    modelId: str | None = None
    purpose: Literal['assistant', 'report', 'asr'] = 'assistant'
    draftVersion: str = Field(min_length=1, max_length=80)


class Selection(Input):
    serviceId: str
    modelId: str
    presetId: str | None = None
    streaming: bool = True


class RoutingInput(Input):
    expectedRevision: int = Field(ge=0)
    assistant: Selection | None = None
    report: Selection | Literal['follow'] | None = 'follow'
    asr: Selection | None = None


class RetryJob(Input):
    useCurrentConfig: bool = False
