import json
import math
import re
from app.core.schemas import Input
from pydantic import Field, model_validator
from typing import Literal

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
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()) > 4096:
        raise ValueError('推理参数必须是 4 KiB 以内的 JSON 对象')
    walk(value)
    return value


class Reasoning(Input):
    efforts: list[str] = Field(default_factory=list, max_length=16)
    initial: str | None = None
    parameterOverrides: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid(self):
        from app.modules.model_services.reasoning.policy import validate_effort
        if len(set(self.efforts)) != len(self.efforts):
            raise ValueError('思考强度不能重复')
        if (self.efforts and self.initial not in self.efforts) or (not self.efforts and self.initial is not None):
            raise ValueError('初始强度必须属于可选强度')
        if set(self.parameterOverrides) - set(self.efforts):
            raise ValueError('参数覆盖只能使用已配置的强度')
        for effort in self.efforts:
            if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', effort):
                raise ValueError('思考强度需为实际档位，例如 low、high 或 max')
            if effort in self.parameterOverrides:
                validate_effort(effort, parameters(self.parameterOverrides[effort]))
        return self


class ServiceModel(Input):
    id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    protocol: Literal['chat', 'transcriptions', 'qwen-asr', 'dashscope-asr'] = 'chat'
    # UI selection mode; execution always uses the saved concrete protocol.
    protocolMode: Literal['auto', 'manual'] = 'manual'
    reasoning: Reasoning = Field(default_factory=Reasoning)
    parameters: dict = Field(default_factory=dict)
    explicitReasoning: bool = False
    streaming: bool = True
    language: str = Field(default='', pattern=r'^[a-zA-Z-]{0,20}$')
    contextWindow: int | None = Field(default=None, ge=1, le=10000000, strict=True)
    contextCapability: dict | None = Field(default=None, exclude=True)

    @model_validator(mode='after')
    def valid(self):
        if any(ord(c) < 32 for c in self.model) or not self.model.strip():
            raise ValueError('模型 ID 无效')
        parameters(self.parameters)
        if self.protocol != 'chat' and (self.reasoning.efforts or self.parameters):
            raise ValueError('语音接口不接受聊天推理参数')
        from app.modules.model_services.reasoning.policy import effort_options
        for effort in self.reasoning.efforts:
            effort_options(self.model_dump(), effort)
        if self.protocol == 'dashscope-asr' and self.language:
            raise ValueError('阿里原生语音转写使用自动语言识别，请清空识别语言')
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
        if any(ord(c) < 32 or ord(c) > 126 for c in self.apiKey):
            raise ValueError('API 密钥只能包含可打印 ASCII 字符')
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
    parameters: dict | None = None
    explicitReasoning: bool = False

    @model_validator(mode='before')
    @classmethod
    def discard_legacy_streaming(cls, value):
        # Old clients and saved drafts may still send this former override.
        # Model settings are now the only source for new task bindings.
        return {key: item for key, item in value.items() if key != 'streaming'} if isinstance(value, dict) else value

    @model_validator(mode='after')
    def valid(self):
        if self.parameters is not None:
            parameters(self.parameters)
        return self


class RoutingInput(Input):
    expectedRevision: int = Field(ge=0)
    assistant: Selection | None = None
    report: Selection | Literal['follow'] | None = 'follow'
    asr: Selection | None = None


class RetryJob(Input):
    useCurrentConfig: bool = False
