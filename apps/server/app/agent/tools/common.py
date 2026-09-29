import json
from fastapi import HTTPException
from app.security.ownership import owned


def clip(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def text_page(fields, start=0, width=1500):
    """Keep JSON intact; the offset applies to each named text field."""
    start = max(0, start)
    values = {key: str(value or '') for key, value in fields.items()}
    size = max((len(value) for value in values.values()), default=0)
    return {key: value[start:start + width] for key, value in values.items()}, {
        'contentOffset': start,
        'contentTruncated': start > 0 or size > width,
        'nextContentOffset': start + width if size > start + width else None,
    }


async def referenced_record(db, model, identifier, actor):
    """Keep model-supplied reference errors recoverable without widening access."""
    try:
        return await owned(db, model, identifier, actor)
    except HTTPException as error:
        if error.status_code != 404:
            raise
        return None
