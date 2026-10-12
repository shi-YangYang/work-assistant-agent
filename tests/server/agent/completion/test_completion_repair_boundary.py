"""Internal completion repairs keep the original request as the user-facing task."""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agent.prompts.main import main_policy
from _support.agent.fakes import completion
from _support.agent.response_delivery import DeliveryModel, run
from _support.agent.completion_repair_boundary import MislabelledReadModel

pytestmark = pytest.mark.asyncio


async def test_false_business_flag_repairs_metadata_without_creating_work_or_reporting_control_messages(setup):
    answer = '注意范围、来源和时效。\n\n[参考文档](https://example.org/guide)'
    fake = MislabelledReadModel(model='controlled', api_key='unused', answer=answer)
    result, stored = await run(setup, fake, '整理三条注意事项，不要保存报告。')
    assert result['reply'] == answer and result['job']['taskOutcome']['state'] == 'completed'
    assert not result['actions'] and not result['interactions']
    assert stored['deliveryRepairs'] == ['action'] and len(fake.repairs) == 1
    assert not stored['incompleteTask'] and fake.calls == 3
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []
