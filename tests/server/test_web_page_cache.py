import asyncio
import httpx
import pytest
from app.integrations.web_page_cache import WebPageCache
from app.integrations.web_research import web_fetch, WebResearchError

pytestmark = pytest.mark.asyncio


async def test_one_download_for_three_slices_and_concurrent_requests():
    requests = []
    async def response(request):
        requests.append(request)
        await asyncio.sleep(.01)
        return httpx.Response(200, text='alpha ' + 'body ' * 1000 + 'omega', headers={'content-type': 'text/plain'})
    transport = httpx.MockTransport(response)
    cache = WebPageCache()
    first, second = await asyncio.gather(web_fetch('https://example.org/page#a', cache=cache, transport=transport), web_fetch('https://example.org/page#b', find='omega', cache=cache, transport=transport))
    third = await web_fetch('https://example.org/page', offset=100, cache=cache, transport=transport)
    assert len(requests) == 1
    assert first['fetchedAt'] == second['fetchedAt'] == third['fetchedAt']
    assert not first['cacheHit'] and second['cacheHit'] and third['cacheHit']
    assert first['requestedUrl'].endswith('#a')
    await cache.close()
    assert not cache.pages and cache.bytes == 0


async def test_refresh_expiry_eviction_and_new_context_redownload():
    now, calls = [0], []
    cache = WebPageCache(max_pages=2, max_bytes=180, ttl=120, clock=lambda: now[0])
    async def load():
        calls.append(1)
        return {'text': '中文' * 10, 'links': [{'url': 'https://example.org'}]}
    assert not (await cache.get('a', load))[1]
    assert (await cache.get('a', load))[1]
    assert not (await cache.get('a', load, refresh=True))[1]
    now[0] = 121
    assert not (await cache.get('a', load))[1]
    await cache.get('b', load)
    await cache.get('c', load)
    assert cache.bytes <= 180 and len(cache.pages) <= 2
    assert not (await cache.get('a', load))[1]
    assert not (await WebPageCache().get('a', load))[1]


async def test_failures_oversize_and_blocked_urls_never_cached_as_success():
    cache, calls = WebPageCache(max_bytes=200), []
    async def fail():
        calls.append(1)
        raise ValueError('not fetched')
    for _ in range(2):
        with pytest.raises(ValueError):
            await cache.get('x', fail)
    assert len(calls) == 2 and not cache.pages
    async def oversized():
        return {'links': ['x' * 1000], 'text': 'tiny'}
    await cache.get('x', oversized)
    assert not cache.pages
    with pytest.raises(WebResearchError):
        await web_fetch('http://127.0.0.1/private', cache=cache)


async def test_cancelled_waiter_does_not_retain_failed_download():
    cache = WebPageCache()
    started, release = asyncio.Event(), asyncio.Event()
    async def load():
        started.set()
        await release.wait()
        raise ValueError('controlled failed download')
    waiter = asyncio.create_task(cache.get('page', load))
    await started.wait()
    download = cache.pending['page']
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    with pytest.raises(ValueError):
        await download
    assert not cache.pending and not cache.pages
    await cache.close()
