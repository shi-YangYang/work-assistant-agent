"""Optional protocol deltas. No business or persistence knowledge belongs here."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDelta:
    index: int
    name: str = ''
    arguments: str = ''
    id: str = ''


@dataclass(frozen=True)
class ModelDelta:
    text: str = ''
    tools: tuple[ToolDelta, ...] = ()
    reasoning: bool = False


def tool_arguments(raw):
    """Full JSON validation must agree with previews, including duplicate keys."""
    import json
    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON key')
            value[key] = item
        return value
    def invalid_constant(_):
        raise ValueError('Invalid JSON constant')
    return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
