import base64
import re
from paa_server.integrations.models import transport
from paa_server.integrations.models.chat import token_usage
from paa_server.integrations.models.transport import ProviderError, normalize_url, status_error
from urllib.parse import urlsplit


def dashscope_asr_endpoint(base):
    # Keep the configured origin and any gateway prefix. Native ASR can share
    # a service's OpenAI-compatible Base URL, without another host or API key.
    if base.endswith('/compatible-mode/v1'):
        base = base[:-len('/compatible-mode/v1')] + '/api/v1'
    elif not urlsplit(base).path:
        base += '/api/v1'
    return base + '/services/aigc/multimodal-generation/generation'


def dashscope_asr_text(data):
    # Token Plan returns text directly; DashScope may wrap it in output.
    for _ in range(3):
        if not isinstance(data, dict):
            break
        if isinstance(data.get('text'), str):
            return data['text']
        sentence = data.get('sentence')
        if isinstance(sentence, dict) and isinstance(sentence.get('text'), str):
            return sentence['text']
        data = data.get('output')
    return None


async def transcribe(settings, config, key, wav, *, on_event=None):
    if len(wav) > 6 * 1024 * 1024:
        raise ProviderError('limit', '规范化语音超过上传限制，请缩短语音')
    base = normalize_url(config['baseUrl'], settings)
    if urlsplit(base).hostname == 'token-plan.cn-beijing.maas.aliyuncs.com':
        model = config['model']
        if re.fullmatch(r'qwen3-asr-flash(?:-.*)?', model) or model == 'qwen-audio-3.0-asr-flash-streaming':
            raise ProviderError('protocol', 'Token Plan 的语音识别请配置 qwen-audio-3.0-asr-flash，并选择阿里原生语音转写接口；修改后点击“使用当前配置重新处理”')
        if re.fullmatch(r'qwen-audio-3\.0-asr-flash(?:-\d{4}-\d{2}-\d{2})?', model) and config['protocol'] != 'dashscope-asr':
            raise ProviderError('protocol', '此 Token Plan 语音模型需要阿里原生语音转写接口；修改后点击“使用当前配置重新处理”')
    if on_event:
        await on_event('started')
    async with transport.client(settings) as http:
        headers = {'Authorization': f'Bearer {key}'}
        if config['protocol'] == 'transcriptions':
            fields = {'model': config['model'], 'response_format': 'json'}
            if config.get('language'):
                fields['language'] = config['language']
            response = await http.post(base + '/audio/transcriptions', headers=headers, data=fields, files={'file': ('speech.wav', wav, 'audio/wav')})
        elif config['protocol'] == 'dashscope-asr':
            if config.get('language'):
                raise ProviderError('protocol', '阿里原生语音转写使用自动语言识别，请清空识别语言')
            body = {
                'model': config['model'],
                'input': {'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': 'data:audio/wav;base64,' + base64.b64encode(wav).decode()}}]}]},
                'parameters': {'format': 'wav', 'sample_rate': '16000'},
            }
            response = await http.post(dashscope_asr_endpoint(base), headers={**headers, 'X-DashScope-SSE': 'disable'}, json=body)
        elif config['protocol'] == 'qwen-asr':
            body = {'model': config['model'], 'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': 'data:audio/wav;base64,' + base64.b64encode(wav).decode()}}]}], 'stream': False}
            if config.get('language'):
                body['asr_options'] = {'language': config['language']}
            response = await http.post(base + '/chat/completions', headers=headers, json=body)
        else:
            raise ProviderError('protocol', '请选择支持的语音转写协议')
        status_error(response)
        data = response.json()
        if on_event:
            await on_event('usage', data.get('usage'))
        if config['protocol'] == 'dashscope-asr':
            text = dashscope_asr_text(data)
        elif config['protocol'] == 'transcriptions':
            text = data.get('text')
        else:
            text = data['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ProviderError('invalid_response', '语音接口没有返回有效文字')
        return text, token_usage(data.get('usage'))
