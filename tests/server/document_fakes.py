"""Fixed responses drive real file tools. No external model calls or work writes."""
import json
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from fakes import ReviewedFixtureModel
from pydantic import Field


class DocumentModel(ReviewedFixtureModel):
    seen: list = Field(default_factory=list, exclude=True)
    query: str = ''

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        def call(name, args):
            return AIMessage(content='', tool_calls=[{'id': 'sample-' + name, 'name': name, 'args': args}])
        if isinstance(last, HumanMessage):
            reply = call('find_documents', {'query': ''})
        elif isinstance(last, ToolMessage) and last.name == 'find_documents':
            data = json.loads(last.content)
            if 'attachment' in data:
                self.seen.append(data)
                row = data['items'][0] if data['items'] else None
                reply = AIMessage(content='仅查看匹配片段：' + (row['text'] + row['citation'] if row else '没有匹配片段。'))
            elif data['items']:
                item = next((row for row in data['items'] if row['name'].endswith('.txt')), data['items'][0])
                reply = call('find_documents', {'attachment_id': item['id'], 'query': self.query}) if self.query else call('read_document', {'attachment_id': item['id'], 'start': 0})
            else:
                reply = AIMessage(content='没有可读取文件。')
        elif isinstance(last, ToolMessage) and last.name == 'read_document':
            data = json.loads(last.content); self.seen.append(data)
            row = data['items'][0] if data['items'] else None
            reply = AIMessage(content='已查看样本的部分文字，供演示使用。' + (row['citation'] if row else '该文件没有可读文字。') + '需要总结还是提取安排？')
        else:
            reply = AIMessage(content='样本已保存。')
        return ChatResult(generations=[ChatGeneration(message=reply)])


def document_model(query=''):
    return DocumentModel(model='controlled-documents', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, query=query)
