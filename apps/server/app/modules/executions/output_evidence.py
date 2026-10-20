"""Small, exact output excerpts piggyback on files already fetched for publication."""
import codecs

PREVIEW_CHARS = 4000


def file_results(files, payloads):
    remaining, results = PREVIEW_CHARS, []
    for file, (_, data) in zip(files, payloads, strict=True):
        if remaining <= 0:
            break
        if file['mimeType'] not in ('application/json', 'text/csv'):
            continue
        # Bound decoding too: one UTF-8 character uses at most four bytes.
        prefix = data[:remaining * 4 + 4]
        try:
            text = codecs.getincrementaldecoder('utf-8-sig')().decode(prefix, final=len(prefix) == len(data))
        except UnicodeDecodeError:
            continue
        content = text[:remaining]
        results.append({'fileId': file['id'], 'name': file['name'], 'mimeType': file['mimeType'],
                        'sha256': file['sha256'], 'content': content,
                        'truncated': len(prefix) < len(data) or len(text) > remaining,
                        'evidenceType': 'generated_file', 'untrusted': True})
        remaining -= len(content)
    return results
