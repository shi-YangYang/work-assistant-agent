"""Exercise the exposed read_file tool through the production graph boundary."""
import pytest
from deepagents.backends.utils import create_file_data
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from fakes import ReviewedFixtureModel, completion
from app.agent.harness import build_graph
from app.tasks.context import RunContext
from app.tasks.runtime.queue import claim
from test_company import send


class VirtualReadModel(ReviewedFixtureModel):
    path: str

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            reply = completion(messages[-1].content)
        else:
            reply = AIMessage(content='', tool_calls=[{
                'id': 'virtual-read', 'name': 'read_file',
                'args': {'file_path': self.path, 'offset': 0, 'limit': 20},
            }])
        return ChatResult(generations=[ChatGeneration(message=reply)])


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/context.txt', '/etc/passwd'])
async def test_read_file_uses_only_this_graph_virtual_files(setup, path):
    settings, sessions, users, clients = setup
    await send(clients['employee'], '读取本次任务的临时材料')
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    model = VirtualReadModel(model='controlled-test', api_key='test-no-network', path=path)
    graph = build_graph(settings, None, context, model)
    state = await graph.ainvoke({
        'messages': [HumanMessage(content='读取本次任务的临时材料')],
        'files': {'/context.txt': create_file_data('gross: 300\nrefunds: 50\nnet: 250')},
    }, context=context)
    reads = [message for message in state['messages'] if isinstance(message, ToolMessage) and message.name == 'read_file']
    assert len(reads) == 1
    if path == '/context.txt':
        assert all(value in reads[0].content for value in ('gross: 300', 'refunds: 50', 'net: 250'))
    else:
        assert 'not found' in reads[0].content.lower()
        assert 'root:' not in reads[0].content
