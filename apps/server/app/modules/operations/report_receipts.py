"""Bounded, version-bound report evidence captured with the business write."""

FIELDS = ('completed', 'ongoing', 'blockers', 'next')
EXCERPT_CHARS = 240


def snapshot(report, *, candidate=False):
    content = (report.candidate or {}).get('content', {}) if candidate else report.content
    values = {name: content.get(name, '') for name in FIELDS}
    # Reports use four strings. An unexpected legacy shape is unknown, not an
    # authenticated empty field; never stringify it into a claimed result.
    lengths = {name: len(value) if isinstance(value, str) else None for name, value in values.items()}
    return {'revision': report.revision, 'status': 'candidate' if candidate else 'saved',
            'publishedRevision': report.published_revision,
            'content': {name: value[:EXCERPT_CHARS] if isinstance(value, str) else None for name, value in values.items()},
            'fieldChars': lengths,
            'emptyFields': [name for name, value in values.items() if isinstance(value, str) and not value.strip()],
            'truncatedFields': [name for name, length in lengths.items() if length is not None and length > EXCERPT_CHARS]}
