"""Effective routing for new tasks; immutable job bindings stay untouched."""

EMPTY_CHOICES = {'assistant': None, 'report': 'follow', 'asr': None, 'image': None}


def unified_choices(stored=None):
    choices = {
        purpose: {key: value for key, value in choice.items() if key != 'streaming'}
        if isinstance(choice, dict) else choice
        for purpose, choice in {**EMPTY_CHOICES, **(stored or {})}.items()
    }
    # Older installations may only have assigned a report model. Keep its model
    # identity, while taking request parameters from the model's own settings.
    if not choices['assistant'] and isinstance(choices['report'], dict):
        choices['assistant'] = {key: choices['report'][key] for key in ('serviceId', 'modelId')}
    choices['report'] = 'follow'
    return choices
