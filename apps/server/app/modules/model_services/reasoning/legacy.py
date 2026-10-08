"""Read-only conversion of old model revisions and migration input.

Old identifiers exist only at this boundary. New configs and bindings carry actual
provider parameters and effort strings, never a named parameter bundle.
"""
from copy import deepcopy


def legacy_parameters(model, selected):
    if 'legacyParameters' in model:
        return deepcopy(model['legacyParameters'])
    preset = next((p for p in model.get('presets', []) if p['id'] == selected), None)
    if selected and not preset:
        raise ValueError('历史推理配置不存在')
    if not preset:
        return {}
    return {'reasoning_effort': preset['value']} if preset.get('mode', 'simple') == 'simple' else deepcopy(preset.get('parameters', {}))


def direct_model(model, selected=None, *, selection_supplied=False):
    if 'presets' not in model and 'selectedPresetId' not in model:
        return deepcopy(model)
    result = {k: deepcopy(v) for k, v in model.items() if k not in ('presets', 'selectedPresetId', 'legacyParameters')}
    chosen = selected if selection_supplied else model.get('selectedPresetId')
    exposed = [p for p in model.get('presets', []) if p.get('assistantEffort')]
    selected_preset = next((p for p in exposed if p['id'] == chosen), None)
    # Existing exposed configs already require an exposed assistant initial choice.
    # Other (pre-exposure) configs retain their exact selected parameters.
    initial = selected_preset['assistantEffort'] if selected_preset else None
    if exposed and initial is None:
        exposed = []
    overrides = {p['assistantEffort']: legacy_parameters(model, p['id']) for p in exposed}
    result['parameters'] = legacy_parameters(model, chosen)
    result['explicitReasoning'] = bool(chosen)
    result['reasoning'] = {'efforts': list(overrides), 'initial': initial, 'parameterOverrides': overrides}
    return result


def migrated_choices(choices, models):
    result = deepcopy(choices)
    for purpose, choice in result.items():
        if not isinstance(choice, dict):
            continue
        model = models.get((choice['serviceId'], choice['modelId']))
        if 'presetId' not in choice:
            continue
        old = choice.pop('presetId', None)
        if purpose == 'report' and model is not None:
            choice['parameters'] = legacy_parameters(model, old)
            choice['explicitReasoning'] = bool(old)
    return result


def legacy_reference_effort(reference, models):
    if 'presetId' not in reference:
        return reference.get('effort')
    selected = reference.get('presetId')
    if selected is None:
        return None
    model = models.get((reference.get('serviceId'), reference.get('modelId')), {})
    preset = next((p for p in model.get('presets', []) if p['id'] == selected), None)
    return preset.get('assistantEffort') if preset else None


from pydantic import Field
from app.core.schemas import Input


class LegacyReasoningReference(Input):
    # Only message idempotency accepts this obsolete wire shape. Never emit it.
    presetId: str | None = Field(default=None, max_length=80)
    preferenceRevision: int = Field(ge=0)
    configVersion: str = Field(min_length=1, max_length=128)
