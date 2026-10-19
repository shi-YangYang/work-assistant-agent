"""Bounded progress journal. Request IDs identify replay, never progress."""
import copy

VERSION = 2
HISTORY = 32
WARN_AFTER = 2
STOP_AFTER = 6


def create(scope):
    return {'version': VERSION, 'scope': scope, 'calls': [], 'seen': [], 'stalled': 0, 'stopped': False}


def admit(state, identifier, request, dependencies, *, prevent_duplicate=False, exhausted=False):
    value = copy.deepcopy(state)
    replay = next((row for row in value['calls'] if row['id'] == identifier), None)
    if replay:
        return value, replay.get('decision', 'execute')
    duplicate = prevent_duplicate and any(row['request'] == request and row['dependencies'] == dependencies
        and row.get('decision') == 'execute' and row.get('executed') is not False for row in value['calls'])
    decision = 'stop' if value['stopped'] else 'repeat' if duplicate or exhausted else 'execute'
    value['calls'] = [*value['calls'], {'id': identifier, 'request': request, 'dependencies': dependencies, 'decision': decision}][-HISTORY:]
    if decision != 'execute':
        value['stalled'] += 1
        value['stopped'] = value['stopped'] or value['stalled'] >= STOP_AFTER
        if value['stopped']:
            decision = value['calls'][-1]['decision'] = 'stop'
    return value, decision


def complete(state, identifier, result, dependencies, *, failed=False, executed=True, no_progress=False, soft_stall=False):
    value = copy.deepcopy(state)
    row = next((row for row in value['calls'] if row['id'] == identifier), None)
    if row is None or row.get('result'):
        return value, False
    row.update(result=result, dependencies=dependencies, executed=executed)
    repeated = failed or no_progress or result in value['seen']
    if repeated and soft_stall:
        # A distinct research attempt can find no evidence without being a
        # repeated operation. It neither consumes nor resets the hard counter.
        row['softStall'] = True
    else:
        value['stalled'] = value['stalled'] + 1 if repeated else 0
    value['seen'] = [*value['seen'], result][-HISTORY:]
    value['stopped'] = value['stopped'] or value['stalled'] >= STOP_AFTER
    return value, repeated and (soft_stall or value['stalled'] >= WARN_AFTER)
