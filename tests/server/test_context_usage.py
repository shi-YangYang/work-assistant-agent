from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from app.agent.context.context_usage import compression_reason, estimate_request, ensure_input
from app.integrations.models.capabilities import capability
from app.modules.model_services.schemas import ServiceModel
from app.tasks.context import BudgetExceeded


def context(window=1000000, input_limit=None):
    return SimpleNamespace(model_purpose='assistant', model_binding={'assistant': {'contextCapability': {'contextWindow': window, 'inputLimit': input_limit, 'source': 'override'}}})


def test_provider_scoped_capacity_and_override():
    assert capability('https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'deepseek-v4.1-flash')['contextWindow'] == 1000000
    assert capability('https://dashscope.aliyuncs.com/compatible-mode/v1', 'vanchin/deepseek-v4.1-flash')['contextWindow'] == 1048576
    assert capability('https://unknown.invalid/v1', 'deepseek-v4.1-flash')['contextWindow'] is None
    assert capability('https://unknown.invalid/v1', 'alias', 65536)['source'] == 'override'
    model = ServiceModel(id='m', model='alias', contextWindow=1000000, contextCapability={'contextWindow': 42})
    assert model.model_dump()['contextWindow'] == 1000000 and 'contextCapability' not in model.model_dump()
    for value in (0, -1, 1.5, True, 10000001):
        with pytest.raises(ValueError):
            ServiceModel(id='m', model='alias', contextWindow=value)


def test_estimate_counts_system_tools_arguments_results_not_base64():
    messages = [SystemMessage(content='系统规则'), HumanMessage(content='您好')]
    plain = estimate_request(messages)
    assert estimate_request(messages, [{'type': 'function', 'function': {'name': 'tool', 'parameters': {'description': '很多参数' * 100}}}]) > plain + 400
    assert estimate_request([*messages, AIMessage(content='', tool_calls=[{'id': '1', 'name': 'tool', 'args': {'text': '查询' * 100}}]), ToolMessage(content='返回' * 100, tool_call_id='1')]) > plain + 400
    image = lambda size: HumanMessage(content=[{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'x' * size}}])
    assert estimate_request([image(100)]) == estimate_request([image(100000)])


def test_exact_ninety_percent_and_output_or_input_reserve():
    ctx = context()
    assert compression_reason(ctx, 899999) is None
    assert compression_reason(ctx, 900000)
    ensure_input(ctx, 700000)
    assert compression_reason(context(1000000, 800000), 810000)
    assert compression_reason(context(10000), 7000, 4000)
    with pytest.raises(BudgetExceeded):
        ensure_input(context(10000), 9000, 4000)
    assert compression_reason(context(None), 2000000) is None
