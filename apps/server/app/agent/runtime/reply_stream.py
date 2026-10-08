"""Lexically decode a JSON string without executing partial tool calls."""
import json
from app.integrations.models.transport import ProviderError


def allows_reply_stream(messages, job_id, payload):
    """Corrective responses remain private until final validation."""
    from langchain_core.messages import HumanMessage
    private_repairs = {f'delivery-repair:{job_id}', f'delivery-references:{job_id}', f'completion-repair:{job_id}'}
    latest = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
    return latest is None or latest.id not in private_repairs


class JsonStringPrefix:
    """Incremental JSON lexer/grammar; expose only a named root string value."""
    def __init__(self, key):
        self.key = key
        self.raw, self.text, self.token = '', '', ''
        self.stack = []
        self.mode, self.escape, self.unicode = '', False, None
        self.high = None
        self.target = False
        self.started = self.complete = False

    def fail(self):
        raise ValueError('Invalid incremental JSON')

    def value(self):
        if not self.stack:
            self.fail()
        frame = self.stack[-1]
        if frame['state'] not in ('value', 'first'):
            self.fail()
        frame['state'] = 'end'

    def character(self, char):
        code = ord(char)
        if self.high is not None:
            if not 0xDC00 <= code <= 0xDFFF:
                self.fail()
            char = chr(0x10000 + ((self.high - 0xD800) << 10) + code - 0xDC00)
            self.high = None
        elif 0xD800 <= code <= 0xDBFF:
            self.high = code
            return
        elif 0xDC00 <= code <= 0xDFFF:
            self.fail()
        self.token += char
        if self.target:
            self.text += char

    def feed(self, chunk):
        if not isinstance(chunk, str):
            self.fail()
        self.raw += chunk
        for char in chunk:
            if self.mode == 'string':
                if self.unicode is not None:
                    if char not in '0123456789abcdefABCDEF':
                        self.fail()
                    self.unicode += char
                    if len(self.unicode) == 4:
                        self.character(chr(int(self.unicode, 16)))
                        self.unicode = None
                    continue
                if self.escape:
                    self.escape = False
                    if char == 'u':
                        self.unicode = ''
                    elif char in '"\\/bfnrt' and self.high is None:
                        self.character({'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}.get(char, char))
                    else:
                        self.fail()
                    continue
                if char == '\\':
                    self.escape = True
                    continue
                if self.high is not None:
                    self.fail()
                if char == '"':
                    self.mode = ''
                    frame = self.stack[-1]
                    if frame['state'] in ('key', 'first') and frame['kind'] == '{':
                        if self.token in frame['keys']:
                            self.fail()
                        frame['keys'].add(self.token)
                        frame['key'], frame['state'] = self.token, 'colon'
                    else:
                        self.value()
                    self.target = False
                elif ord(char) < 32:
                    self.fail()
                else:
                    self.character(char)
                continue
            if self.mode == 'scalar':
                if char not in ',]} \r\n\t':
                    self.token += char
                    continue
                self.scalar()
            if char in ' \r\n\t':
                continue
            if self.complete:
                self.fail()
            if not self.started:
                if char != '{':
                    self.fail()
                self.started = True
                self.stack.append({'kind': '{', 'state': 'first', 'keys': set(), 'key': None})
                continue
            frame = self.stack[-1]
            state, kind = frame['state'], frame['kind']
            target = len(self.stack) == 1 and state == 'value' and frame.get('key') == self.key
            if char == '"':
                if state not in (('first', 'key', 'value') if kind == '{' else ('first', 'value')):
                    self.fail()
                self.mode, self.token, self.target = 'string', '', target
            elif char in '{[':
                if target:
                    self.fail()
                self.value()
                if len(self.stack) >= 64:
                    self.fail()
                self.stack.append({'kind': char, 'state': 'first', 'keys': set(), 'key': None})
            elif char in '}]':
                if char != ('}' if kind == '{' else ']') or state not in ('first', 'end'):
                    self.fail()
                self.stack.pop()
                self.complete = not self.stack
            elif char == ':' and kind == '{' and state == 'colon':
                frame['state'] = 'value'
            elif char == ',' and state == 'end':
                frame['state'] = 'key' if kind == '{' else 'value'
            elif state in ('value', 'first') and (kind == '[' or state == 'value') and not target:
                self.mode, self.token = 'scalar', char
            else:
                self.fail()
        return self.text

    def scalar(self):
        try:
            value = json.loads(self.token, parse_constant=lambda _: self.fail())
            if isinstance(value, (str, list, dict)):
                self.fail()
        except (ValueError, TypeError):
            self.fail()
        self.mode = ''
        self.value()

    def finish(self):
        if not self.complete or self.mode or self.escape or self.high is not None:
            self.fail()
        value = json.loads(self.raw)
        if not isinstance(value.get(self.key), str):
            self.fail()
        return value


class ReplyCandidate:
    """Preview marked final prose or a legacy completion; tool batches stay private."""
    def __init__(self, publisher):
        self.publisher = publisher
        self.calls = {}
        self.parser = None
        self.invalid = False
        self.prose = ''
        self.prose_visible = False
        self.mixed_prose = False

    async def feed(self, delta):
        try:
            self.prose += delta.text
            if delta.tools and self.prose_visible:
                # A premature final-answer marker cannot make tool preamble a
                # final reply. Retire its preview, but still validate/execute tools.
                self.mixed_prose = True
                await self.publisher.withdraw()
                self.prose_visible = False
            for fragment in delta.tools:
                call = self.calls.setdefault(fragment.index, {'name': '', 'arguments': ''})
                call['name'] += fragment.name
                call['arguments'] += fragment.arguments
            if not self.calls:
                from app.agent.completion.prose import parse_header
                text, _, marked = parse_header(self.prose)
                if marked and text:
                    self.prose_visible = True
                    await self.publisher.write(text)
                return
            if len(self.calls) != 1:
                if self.parser or any(c['name'] == 'finish_task' for c in self.calls.values()):
                    raise ValueError('Mixed completion')
                return
            call = next(iter(self.calls.values()))
            if call['name'] != 'finish_task':
                if self.parser:
                    raise ValueError('Changed completion name')
                return
            if self.parser is None:
                self.parser = JsonStringPrefix('answer')
                text = self.parser.feed(call['arguments'])
            else:
                text = self.parser.feed(''.join(f.arguments for f in delta.tools))
            await self.publisher.write(text)
        except ValueError:
            self.invalid = True
            await self.publisher.withdraw()
            raise ProviderError('invalid_response', '模型未返回完整有效的收尾参数') from None

    @property
    def text(self):
        if self.parser:
            return self.parser.text
        if self.prose_visible and not self.calls:
            from app.agent.completion.prose import parse_header
            return parse_header(self.prose)[0]
        return None

    async def finish(self):
        if not self.calls:
            from app.agent.completion.prose import parse_header
            try:
                text, _, _ = parse_header(self.prose, complete=True)
            except ValueError:
                await self.publisher.withdraw()
                raise ProviderError('invalid_response', '模型未返回完整有效的正文标记') from None
            if text:
                await self.publisher.write(text, state='finalizing', force=True)
        if self.parser:
            try:
                self.parser.finish()
            except ValueError:
                await self.publisher.withdraw()
                raise ProviderError('invalid_response', '模型未返回完整有效的收尾参数') from None
            await self.publisher.write(self.parser.text, state='finalizing', force=True)
