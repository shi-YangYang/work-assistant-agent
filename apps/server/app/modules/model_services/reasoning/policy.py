"""Direct effort choices and provider parameters; no independent presets."""
import re
from copy import deepcopy


def validate_effort(effort, options):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', effort):
        raise ValueError('思考强度需为实际档位，例如 low、high 或 max')
    reasoning = options.get('reasoning')
    values = [options['reasoning_effort']] if 'reasoning_effort' in options else []
    if isinstance(reasoning, dict) and 'effort' in reasoning:
        values.append(reasoning['effort'])
    thinking = options.get('thinking')
    disabled = options.get('enable_thinking') is False or (isinstance(thinking, dict) and thinking.get('type') in ('disabled', 'off'))
    if not values or any(value != effort for value in values) or disabled:
        raise ValueError('思考强度必须与实际推理参数一致，且不能关闭思考')


def effort_options(model, effort):
    reasoning = model.get('reasoning', {})
    if effort in reasoning.get('parameterOverrides', {}):
        options = deepcopy(reasoning['parameterOverrides'][effort])
    else:
        options = deepcopy(model.get('parameters', {}))
        if isinstance(options.get('reasoning'), dict) and 'effort' in options['reasoning']:
            options['reasoning']['effort'] = effort
            if 'reasoning_effort' in options:
                options['reasoning_effort'] = effort
        else:
            options['reasoning_effort'] = effort
    validate_effort(effort, options)
    return options


def exposed(model):
    return [{'effort': value} for value in model.get('reasoning', {}).get('efforts', [])]


def effective_selection(selection, model, preference):
    options = exposed(model)
    selected = {**selection, 'effort': model.get('reasoning', {}).get('initial')}
    if options and preference and all(preference.get(k) == selection.get(k) for k in ('serviceId', 'modelId')) and any(p['effort'] == preference.get('effort') for p in options):
        selected['effort'] = preference['effort']
    return selected, options
