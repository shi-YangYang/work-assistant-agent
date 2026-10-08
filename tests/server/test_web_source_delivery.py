"""Page-reading receipts reach messages even when the model omits all links."""
import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agent.tools.web import research
from app.integrations import web_research
from app.modules.messages.models import Message
from app.modules.messages.web_sources import web_citations, web_source_dtos
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from fakes import completion
from test_business_actions import runtime
from test_response_delivery import DeliveryModel, model, run


def page(url='https://publisher.example/article', **extra):
    return {'url': url, 'title': '原始报道', 'evidenceType': 'page_text',
            'offset': 0, 'endOffset': 20, 'fetchState': 'read', **extra}


def test_source_projection_deduplicates_reads_and_never_promotes_discovered_links():
    rows = {
        'first': page('https://PUBLISHER.example/article#one'),
        'second': page('https://publisher.example/article#two', title='长' * 500, fetchState='unavailable'),
        'snippet': page('https://publisher.example/search', evidenceType='search_snippet'),
        'link': page('https://publisher.example/discovered', evidenceType='page_link'),
        'empty': page('https://publisher.example/empty', endOffset=0),
        'failed': {'url': 'https://publisher.example/failed', 'fetchState': 'unavailable'},
    }
    result = web_citations({'webSources': rows})
    assert result == [{'kind': 'web', 'url': 'https://publisher.example/article',
                       'title': '长' * 200, 'evidenceType': 'page_text', 'refetchFailed': True}]
    assert web_source_dtos([{'attachmentId': 'attachment'}, {'kind': 'business'}, *result]) == [
        {'url': 'https://publisher.example/article', 'title': '长' * 200, 'refetchFailed': True}]


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'data:text/html,example', 'file:///etc/passwd',
    'http://localhost/a', 'http://127.0.0.1/a', 'http://169.254.169.254/a',
    'http://[::1]/a', 'https://user:password@publisher.example/a',
    'https://publisher.example:8000/a', 'https://publisher.example/\nattack',
])
def test_source_projection_rejects_unsafe_urls_on_write_and_read(url):
    assert web_citations({'webSources': {'unsafe': page(url)}}) == []
    assert web_source_dtos([{'kind': 'web', **page(url)}]) == []


class ResearchModel(DeliveryModel):
    urls: list[str] = Field(default_factory=list)
    deny_after_read: bool = False

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        urls = self.urls if self.calls == 1 else self.urls[:1] if self.calls == 2 and self.deny_after_read else []
        result = AIMessage(content='', tool_calls=[{'name': 'web_fetch', 'id': f'read-{self.calls}-{index}', 'args': {'url': url}}
                                                 for index, url in enumerate(urls)]) if urls else completion(self.answer)
        return ChatResult(generations=[ChatGeneration(message=result)])


@pytest.mark.asyncio
async def test_actual_tool_reads_persist_in_message_dto_without_model_links_and_do_not_leak_to_followup(setup, monkeypatch):
    original = web_research.web_fetch
    counts = {}

    def response(request):
        path = request.url.path
        counts[path] = counts.get(path, 0) + 1
        if counts[path] > 1:
            return httpx.Response(403)
        return httpx.Response(200, headers={'content-type': 'text/html'},
                              text=f'<title>原始报道 {path}</title><main>报道内容。<a href="/unread">未读目标</a></main>')

    async def fetch(url, **kwargs):
        return await original(url, transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(web_research, 'web_fetch', fetch)
    urls = [f'https://publisher.example/article-{index}' for index in range(3)]
    fake = ResearchModel(model='controlled', api_key='unused', urls=urls, deny_after_read=True, answer='已整理三条报道。')
    result, stored = await run(setup, fake, '读取这些报道，整理结果')
    assert result['reply'] == fake.answer and fake.calls == 3, result['job']
    assert {source['url'] for source in result['webSources']} == set(urls)
    assert next(source for source in result['webSources'] if source['url'] == urls[0])['refetchFailed']
    assert all('/unread' != source['url'].split('example')[-1] for source in result['webSources'])
    assert not result['citations'] and not result['businessCitations']
    async with setup[1]() as db:
        message = await db.get(Message, result['id'])
        assert len(message.citations) == 3 and all(row['kind'] == 'web' for row in message.citations)
    refreshed = (await setup[3]['employee'].get('/api/v1/messages/' + result['id'])).json()
    assert refreshed['webSources'] == result['webSources']
    assert (await setup[3]['peer'].get('/api/v1/messages/' + result['id'])).status_code == 404
    followup, _ = await run(setup, model(answer='这是接下来的整理。'), '只根据此前对话改写', conversationId=result['conversationId'])
    assert followup['webSources'] == []
    assert (await setup[3]['employee'].get('/api/v1/messages/' + result['id'])).json()['webSources'] == result['webSources']
    assert stored['webSources'][urls[0]]['evidenceType'] == 'page_text'


@pytest.mark.asyncio
async def test_failed_fetch_does_not_publish_a_source(setup, monkeypatch):
    async def denied(*args, **kwargs):
        raise web_research.WebResearchError('该网页不可用', code='http_403')

    monkeypatch.setattr(web_research, 'web_fetch', denied)
    fake = ResearchModel(model='controlled', api_key='unused', urls=['https://publisher.example/missing'], answer='未取得网页内容。')
    result, _ = await run(setup, fake, '读取公开页面')
    assert result['reply'] == fake.answer and result['webSources'] == []


@pytest.mark.asyncio
async def test_discovery_cache_does_not_evict_read_receipts_and_scope_change_clears_them(setup):
    context, _ = await runtime(setup, '读取公开页面')
    context.node_retry = True
    await initialize(context, 'original-input')

    async def read(_):
        return {**page(), 'text': '成功读到的网页内容。'}

    await research(context, read, 'https://publisher.example/article', is_fetch=True)

    async def discover(_):
        return {'items': [{'url': f'https://publisher.example/discovered-{index}', 'title': '搜索结果', 'evidenceType': 'search_snippet'} for index in range(60)]}

    await research(context, discover, '报道')
    await initialize(context, 'original-input')
    async with context.sessions() as db:
        result = (await db.get(Job, context.job_id)).result
        assert len(result['webSources']) == 41
        assert [source['url'] for source in web_citations(result)] == ['https://publisher.example/article']
    await initialize(context, 'changed-input')
    async with context.sessions() as db:
        assert not (await db.get(Job, context.job_id)).result.get('webSources')
