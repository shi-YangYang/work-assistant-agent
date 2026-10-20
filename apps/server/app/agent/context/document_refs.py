"""Page-reference markers shared by context budgeting and image assembly."""
import json

PAGE_MARKER = 'NORIA_DOCUMENT_PAGES:'


def referenced_pages(messages):
    tokens = []
    for message in messages:
        content = message.get('content')
        if message.get('role') == 'tool' and isinstance(content, str):
            try:
                value = json.loads(content)
                if isinstance(value, dict):
                    tokens.extend(value.get('pageRefs', []))
            except ValueError:
                pass
        if message.get('role') == 'user' and isinstance(content, list):
            for block in content:
                if block.get('type') == 'text' and block.get('text', '').startswith(PAGE_MARKER):
                    try:
                        tokens.extend(json.loads(block['text'][len(PAGE_MARKER):]))
                    except ValueError:
                        pass
    return [token for token in tokens if isinstance(token, str)]
