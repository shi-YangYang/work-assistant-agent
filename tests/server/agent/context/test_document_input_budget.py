"""Optional page pixels must fit the same complete request as model enforcement."""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from app.agent.context import document_input
from app.agent.context.context_usage import estimate_request, ensure_input


def test_human_preload_marker_has_the_same_page_reserve_as_wire_user():
    blocks = [{'type': 'text', 'text': document_input.PAGE_MARKER + json.dumps(['page-one', 'page-two'])}]
    human = [HumanMessage(content=blocks)]
    wire = [{'role': 'user', 'content': blocks}]
    assert estimate_request(human) == estimate_request(wire)
    assert estimate_request(human) - estimate_request(human, document_images=False) == 8192


@pytest.fixture
def page_request(tmp_path, monkeypatch):
    @asynccontextmanager
    async def session():
        yield object()
    cap = {'contextWindow': None, 'inputLimit': 12000}
    context = SimpleNamespace(sessions=session, model_purpose='assistant', model_binding={'assistant': {'contextCapability': cap}})
    item = SimpleNamespace(id='owned', name='owned.pdf')
    ref = {'attachmentId': 'owned', 'page': 1, 'resolution': 'normal', 'sheet': '', 'location': '第 1 页'}
    job = SimpleNamespace(result={'documentPageRequests': {'owned-page': ref}})
    cached = tmp_path / 'owned.png'; cached.write_bytes(b'owned')
    image = {'tiles': [{'mime': 'image/png', 'data': 'AA==', 'box': [0, 0, 1, 1]} for _ in range(2)], 'pixels': 2, 'bytes': 2, 'complete': True}
    monkeypatch.setattr(document_input, 'lease', AsyncMock(return_value=(job, object())))
    monkeypatch.setattr(document_input, 'agent_attachment', AsyncMock(return_value=item))
    monkeypatch.setattr('app.integrations.parsing.document_rendering.page_path', lambda *_: cached)
    monkeypatch.setattr('app.integrations.media.image_process', AsyncMock(return_value=image))
    messages = [{'role': 'user', 'content': 'x' * 2000}, {'role': 'tool', 'content': json.dumps({'pageRefs': ['owned-page']})}]
    tools = [{'type': 'function', 'function': {'name': 'example', 'description': 'x' * 8000, 'parameters': {'type': 'object', 'properties': {}}}}]
    return context, cap, job, messages, tools


@pytest.mark.asyncio
async def test_tool_schemas_and_all_tiles_are_in_the_optional_page_budget(page_request):
    context, cap, _, messages, tools = page_request
    ensure_input(context, estimate_request(messages, tools, document_images=False))
    payload, supplied = await document_input.assemble_pages(context, messages, tools=tools)
    assert not supplied
    assert '尚未提供图片' in str(payload)
    ensure_input(context, estimate_request(payload, tools, document_images=False))
    cap['inputLimit'] = 100000
    full, supplied = await document_input.assemble_pages(context, messages, tools=tools)
    assert list(supplied) == ['owned-page']
    assert sum(block['type'] == 'image_url' for block in full[-1]['content']) == 2
    exact = estimate_request(full, tools, document_images=False)
    # Exact window includes tools, image tiles, source labels and message envelope.
    cap.update(inputLimit=None, contextWindow=exact + 500)
    exact_payload, supplied = await document_input.assemble_pages(context, messages, tools=tools, output_reserve=500)
    assert supplied and exact_payload == full
    ensure_input(context, estimate_request(exact_payload, tools, document_images=False), 500)
    cap['contextWindow'] -= 1
    smaller, supplied = await document_input.assemble_pages(context, messages, tools=tools, output_reserve=500)
    assert not supplied
    ensure_input(context, estimate_request(smaller, tools, document_images=False), 500)


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled', [False, True])
async def test_no_notice_headroom_never_breaks_an_otherwise_valid_text_request(page_request, disabled):
    context, cap, job, messages, tools = page_request
    job.result['documentVisionDisabled'] = disabled
    cap['inputLimit'] = estimate_request(messages, tools, document_images=False)
    payload, supplied = await document_input.assemble_pages(context, messages, tools=tools)
    assert payload == messages and not supplied
    ensure_input(context, estimate_request(payload, tools, document_images=False))
