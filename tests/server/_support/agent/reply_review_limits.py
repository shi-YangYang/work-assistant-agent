"""Shared controlled fixtures extracted from test_reply_review_limits."""
import httpx
from _support.agent.model_stream_errors import stream


CONFIG = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'deepseek-v4.1-flash',
          'streaming': True, 'parameters': {'enable_thinking': True, 'reasoning_effort': 'high', 'temperature': .3}}


def response_for(body, content, finish='stop'):
    # Complete-looking JSON is still invalid when the provider reports length.
    message = {'content': content, 'reasoning_content': 'private reasoning'}
    usage = {'prompt_tokens': 2100, 'completion_tokens': 6000 if finish == 'length' else 60,
             'completion_tokens_details': {'reasoning_tokens': 6000 if finish == 'length' else 0}}
    if body['stream']:
        return stream({'choices': [{'delta': message, 'finish_reason': finish}], 'usage': usage})
    return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', **message}, 'finish_reason': finish}], 'usage': usage})
