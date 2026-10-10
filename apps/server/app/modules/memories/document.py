"""Exact text patches and offset-only provenance; Markdown is the only body."""
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from app.core.errors import problem
from .limits import MAX_CHARACTERS


def validate(markdown):
    if len(markdown) > MAX_CHARACTERS:
        problem(422, '记忆文档最多可保存 6000 个字符', 'memory_capacity')
    # Defense in depth for common credential formats, not a semantic classifier.
    if re.search(r'(?i)(?:\b(?:sk-|ghp_|github_pat_)[\w-]{12,}|-----BEGIN [\w ]*PRIVATE KEY|(?:密码|验证码|口令|密钥|password|api[_ -]?key|access[_ -]?token)\s*[:：=是]\s*\S{3,})', markdown):
        problem(422, '记忆不能保存密码、验证码或密钥等凭证', 'memory_secret')


def blocks(markdown):
    """Blank-line blocks, keeping fenced code and adjacent list items whole."""
    start, offset, fence = None, 0, None
    for line in markdown.splitlines(keepends=True):
        stripped = line.strip()
        marker = re.match(r'^(`{3,}|~{3,})', stripped)
        if stripped and start is None:
            start = offset
        if marker:
            if fence and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            elif fence is None:
                fence = marker[1]
        if not stripped and not fence and start is not None:
            yield start, offset
            start = None
        offset += len(line)
    if start is not None:
        yield start, len(markdown)


def annotations_after(old, markdown, origin, *, source=None, expires=None):
    """Retain each unchanged span's metadata, including reordered content."""
    text = old.get('markdown', '')
    previous = old.get('annotations', [])
    if markdown == text:
        return {**old, 'schemaVersion': 1, 'markdown': markdown,
                'annotations': [dict(row) for row in previous]}
    fresh = {'origin': origin, 'updatedAt': datetime.now(timezone.utc).isoformat(),
             **({'sourceMessage': source} if source else {}), **({'expiresAt': expires} if expires else {})}
    metadata = [fresh] * len(markdown)
    occupied = set()
    mappings, used_blocks = [], set()
    # Match whole moved blocks before the ordered diff. Each annotation inside
    # the block keeps its own metadata, including distinct expiration times.
    old_blocks = list(blocks(text))
    for start, end in blocks(markdown):
        for a, b in old_blocks:
            if a not in used_blocks and text[a:b] == markdown[start:end]:
                mappings.append((a, start, b - a))
                used_blocks.add(a)
                break
    mappings.extend(SequenceMatcher(None, text, markdown, autojunk=False).get_matching_blocks())
    for row in previous:
        a, b = row['start'], row['end']
        candidates = [new + a - old for old, new, size in mappings if old <= a and b <= old + size]
        value = text[a:b]
        if value.strip() and markdown.count(value) == 1:
            candidates.append(markdown.index(value))
        # Inherit a COMPLETE old annotation or none of it. A character edit to
        # an expiring fact must become a complete manual fact, not leave a
        # permanent character surrounded by expiring fragments.
        for start in candidates:
            end = start + b - a
            if not any(index in occupied for index in range(start, end)):
                prior = {key: value for key, value in row.items() if key not in ('start', 'end')}
                metadata[start:end] = [prior] * (b - a)
                occupied.update(range(start, end))
                break
    result = []
    for index, values in enumerate(metadata):
        if result and {key: value for key, value in result[-1].items() if key not in ('start', 'end')} == values:
            result[-1]['end'] = index + 1
        else:
            result.append({'start': index, 'end': index + 1, **values})
    return {'schemaVersion': 1, 'markdown': markdown, 'annotations': result,
            **({'barrierAt': old['barrierAt']} if old.get('barrierAt') else {})}


def fragment_key(text):
    """Compare complete facts, ignoring only list markers and outer whitespace."""
    return '\n'.join(re.sub(r'^(?:[-*+] |\d+[.)] )\s*', '', line.rstrip())
                     for line in text.strip().splitlines())


def already_present(document, new, expires):
    text = document['markdown']
    candidates = []
    scoped = False
    for start, end in blocks(text):
        body = text[start:end].strip()
        # A heading changes scope; identical words under different headings
        # are not interchangeable. Code/quotes are not standalone facts.
        headings = list(re.finditer(r'^#{1,6}\s+.+$', body, re.M))
        if headings:
            scoped = True
        if scoped:
            continue
        if re.search(r'^(?:\s*[>`~]| {4}|\t)', text[start:end], re.M):
            continue
        candidates.append((start, end, body))
        # Adjacent, single-line top-level list items are separate facts.
        lines = text[start:end].splitlines(keepends=True)
        if len(lines) > 1 and all(re.match(r'^(?:[-*+] |\d+[.)] )\S', line) for line in lines):
            offset = start
            for line in lines:
                candidates.append((offset, offset + len(line), line.strip()))
                offset += len(line)
    if re.search(r'^(?:\s*[#>`~]| {4}|\t)', new, re.M):
        # Rich/scoped fragments keep exact block equality; no semantic guessing.
        return any(text[a:b].strip() == new.strip() and all(
            row.get('expiresAt') == expires for row in document.get('annotations', [])
            if row['start'] < b and row['end'] > a) for a, b in blocks(text))
    key = fragment_key(new)
    return any(fragment_key(body) == key and all(
        row.get('expiresAt') == expires for row in document.get('annotations', [])
        if row['start'] < b and row['end'] > a) for a, b, body in candidates)


def patch(document, old, new, *, explicit, source, expires=None):
    text = document['markdown']
    if old:
        if text.count(old) != 1:
            problem(409, '目标记忆已变化或存在多个匹配，请明确要修改的片段', 'memory_patch_conflict')
        start = text.index(old)
        end = start + len(old)
        protected = any(row.get('origin') == 'manual' and row['start'] < end and row['end'] > start for row in document.get('annotations', []))
        if protected and not explicit:
            problem(409, '人工编辑的记忆需要明确的修改要求，未覆盖原文', 'memory_manual_protected')
        if expires and any(a < start < b or a < end < b for a, b in blocks(text)):
            problem(422, '有期限的记忆请修改完整段落或列表，避免影响其它内容')
        # A fragment replacement must not reinsert the surrounding list syntax.
        line_start = text.rfind('\n', 0, start) + 1
        prefix = text[line_start:start]
        fence = None
        for line in text[:line_start].splitlines():
            marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
            if marker and fence is None:
                fence = marker[1]
            elif marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        literal = fence is not None or text[line_start:].startswith(('    ', '\t'))
        if not literal and re.fullmatch(r'[ \t]*(?:[-*+] |\d+[.)] )', prefix):
            new = re.sub(r'^[ \t]*(?:[-*+] |\d+[.)] )', '', new, count=1)
        if not literal and new and end < len(text) and text[end] in '。！？；.!?;' and new.endswith(text[end]):
            new = new[:-1]
        changed = text[:start] + new + text[end:]
    else:
        if not new.strip():
            problem(422, '请输入需要保存的记忆')
        if already_present(document, new, expires):
            return document
        changed = text + ('\n\n' if text and not text.endswith('\n\n') else '') + new
    validate(changed)
    # Preserve exact unaffected offsets even for a patch within a large block.
    start = text.index(old) if old else len(text)
    end = start + len(old)
    delta = len(changed) - len(text)
    annotations = []
    for row in document.get('annotations', []):
        a, b = row['start'], row['end']
        if b <= start:
            annotations.append(dict(row))
        elif a >= end:
            annotations.append({**row, 'start': a + delta, 'end': b + delta})
        else:
            if a < start:
                annotations.append({**row, 'end': start})
            if b > end:
                annotations.append({**row, 'start': start + len(new), 'end': b + delta})
    if new:
        annotations.append({'start': start, 'end': start + (len(changed) - len(text) if not old else len(new)),
                            'origin': 'explicit' if explicit else 'inferred', 'sourceMessage': source,
                            'updatedAt': datetime.now(timezone.utc).isoformat(), **({'expiresAt': expires} if expires else {})})
    return {**document, 'markdown': changed, 'annotations': sorted(annotations, key=lambda row: row['start'])}


def injection(document, budget, *, clock=None):
    """Select complete sections, never cut a sentence/list or lose its heading."""
    clock = clock or datetime.now(timezone.utc)
    text = document.get('markdown', '')
    # Blank expired ranges while retaining offsets for valid neighboring spans.
    # Expiring writes are required to use complete Markdown blocks.
    for row in document.get('annotations', []):
        if row.get('expiresAt') and datetime.fromisoformat(row['expiresAt']) <= clock:
            a, b = row['start'], row['end']
            text = text[:a] + ''.join('\n' if c == '\n' else ' ' for c in text[a:b]) + text[b:]
    candidates, headings = [], []
    for start, end in blocks(text):
        body = text[start:end].rstrip()
        rows = [row for row in document.get('annotations', []) if row['start'] < end and row['end'] > start]
        rows = [row for row in rows if not row.get('expiresAt') or datetime.fromisoformat(row['expiresAt']) > clock]
        lines = body.splitlines()
        # Headings retain enclosing scope for selected sections. A heading with
        # its body is kept whole; standalone headings are carried to descendants.
        prefix = []
        for line in lines:
            match = re.match(r'^(#{1,6})\s+', line)
            if match:
                level = len(match[1])
                headings = [(n, value) for n, value in headings if n < level]
                headings.append((level, line))
            else:
                break
        if all(re.match(r'^#{1,6}\s+', line) for line in lines):
            continue
        prefix = [value for _, value in headings if value not in lines]
        value = '\n'.join(prefix) + ('\n\n' if prefix else '') + body
        priority = max(({'manual': 2, 'explicit': 1}.get(row.get('origin'), 0) for row in rows), default=0)
        recency = max((row.get('updatedAt', '') for row in rows), default='')
        candidates.append((priority, recency, start, value))
    selected, used = [], 0
    for _, _, start, value in sorted(candidates, reverse=True):
        if used + len(value) + 2 <= budget:
            selected.append((start, value)); used += len(value) + 2
    return '\n\n'.join(value for _, value in sorted(selected))


def forget_fragment(markdown, target):
    """Remove a complete exact clause; never infer which adjacent facts to erase."""
    target = target.strip()
    if not target or markdown.count(target) != 1:
        problem(409, '没有唯一匹配的记忆，请明确要忘记的内容', 'memory_patch_conflict')
    start = markdown.index(target)
    end = start + len(target)
    boundaries = [match for match in re.finditer(r'[\n。！？；;,，!?]|\.(?=\s|$)', markdown)
                  if not (match[0] == '.' and re.fullmatch(r'[ \t]*\d+', markdown[markdown.rfind('\n', 0, match.start()) + 1:match.start()]))]
    left = max((match.end() for match in boundaries if match.end() <= start), default=0)
    prefix = markdown[left:start]
    # List markers and indentation belong to the clause, but words such as
    # another subject or a coordinated fact must never be silently included.
    if not re.fullmatch(r'\s*(?:[-*+]\s+|\d+[.)]\s+)?', prefix):
        problem(409, '请用本轮请求中的完整事实定位记忆，包含主体和内容；本次未删除任何内容', 'memory_patch_conflict')
    if left == 0 or markdown[left - 1] == '\n':
        start = left
    if not any(match.end() == end for match in boundaries):
        following = next((match for match in boundaries if match.start() >= end), None)
        right = following.start() if following else len(markdown)
        if markdown[end:right].strip():
            problem(409, '目标只覆盖部分记忆，请明确完整事实；本次未删除任何内容', 'memory_patch_conflict')
        end = following.end() if following else right
    for a, b in blocks(markdown):
        if a <= start < b and not markdown[a:start].strip() and not markdown[end:b].strip():
            start, end = a, max(end, b)
            while end < len(markdown) and markdown[end].isspace():
                end += 1
            if end == len(markdown):
                while start and markdown[start - 1].isspace():
                    start -= 1
            break
    else:
        while end < len(markdown) and markdown[end] in ' \t':
            end += 1
        if (start == 0 or markdown[start - 1] == '\n') and end < len(markdown) and markdown[end] == '\n':
            end += 1
    return markdown[start:end]
