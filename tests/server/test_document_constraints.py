"""Page constraints reach the runner without changing legacy request identity."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.agent.tools.sandbox.documents import create_document
from app.modules.executions.requests import builtin_request


ARGUMENTS = {'filename': '计划.docx', 'title': '项目计划',
             'blocks': [{'type': 'paragraph', 'text': '保留完整正文'}]}


def test_omitted_page_limit_preserves_legacy_request_shape():
    implicit = builtin_request('create_document', ARGUMENTS)
    explicit = builtin_request('create_document', {**ARGUMENTS, 'max_pages': None})
    assert implicit == explicit
    assert set(implicit['arguments']) == {'filename', 'title', 'blocks', 'format'}


@pytest.mark.parametrize('maximum', [0, -1, 41, True, '1', 1.5])
def test_page_limit_rejects_invalid_values(maximum):
    with pytest.raises(ValidationError):
        builtin_request('create_document', {**ARGUMENTS, 'max_pages': maximum})


@pytest.mark.asyncio
async def test_page_limit_reaches_execution_and_failed_result_is_not_success():
    runtime = SimpleNamespace(context=object())
    receipt = {'state': 'failed', 'message': '完整内容超过1页上限；未发布文件'}
    execute = AsyncMock(return_value=receipt)
    with patch('app.agent.tools.sandbox.common.execute', execute):
        result = json.loads(await create_document.coroutine(**ARGUMENTS, runtime=runtime, max_pages=1))
    assert result == receipt and 'delivery' not in result
    assert execute.call_args.kwargs['task']['arguments']['max_pages'] == 1
    assert execute.call_args.kwargs['task']['arguments']['blocks'][0]['text'] == '保留完整正文'
