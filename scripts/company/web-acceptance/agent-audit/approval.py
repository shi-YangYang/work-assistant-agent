"""Only confirm preregistered mutation kinds in the currently authorized user turn."""
import asyncio
from contextvars import ContextVar
import json
from pathlib import Path

current = ContextVar('audit_case', default=None)
KINDS = {'create_work': 'workCreate', 'update_work': 'workUpdate', 'delete_work': 'workDelete', 'generate_report': 'reportCreate', 'edit_report': 'reportUpdate', 'submit_report': 'reportSubmit', 'delete_report': 'reportDelete'}


def allowed(card, bounds, confirmed):
    kind = KINDS.get(card.get('action'))
    return bool(kind and confirmed.get(kind, 0) < bounds.get(kind, 0))


def accepted_turn(http, directory, receipt):
    accepted = http.read_rows(directory / 'recovery-accepted.jsonl') + http.read_rows(directory / 'accepted.jsonl')
    return next(r['turn'] for r in reversed(accepted) if r['receipt']['messageId'] == receipt['messageId'])


def install(http):
    original = http.settle

    async def settle(client, receipt, timeout, *, approve=False, progress=None):
        selected = current.get()
        if not selected:
            return await original(client, receipt, timeout, approve=False, progress=progress)
        case, directory = selected
        turn = accepted_turn(http, directory, receipt)
        bounds = case['mutationBounds'][turn - 1]
        approvals, references, counts = [], {receipt['messageId']: receipt}, {}

        def follow(reference):
            if not reference:
                return False
            if reference.get('conversationId') != receipt['conversationId']:
                raise RuntimeError('Continuation left the authorized conversation')
            if reference['messageId'] in references:
                return False
            references[reference['messageId']] = reference
            if progress:
                progress({'kind': 'continuation', 'receipt': reference})
            return True

        async with asyncio.timeout(timeout):
            while True:
                values = [http.checked(await client.get('/api/v1/messages/' + key)) for key in list(references)]
                cards = {c['id']: c for value in values for c in value.get('actions', [])}
                if any([follow(c.get('continuation')) for c in cards.values()]):
                    continue
                busy = any(v.get('job', {}).get('state') not in http.TERMINAL for v in values)
                # A report action can remain running while its child explicitly
                # awaits a user retry. Observe that terminal failure; do not
                # manufacture 32 minutes of extra waiting or retry the model.
                busy = busy or any(
                    (c.get('job') or {}).get('state') in ('queued', 'running')
                    or c['state'] == 'running' and (c.get('job') or {}).get('state') not in http.TERMINAL
                    for c in cards.values())
                if not busy:
                    pending = [c for c in cards.values() if c['state'] == 'pending' and c.get('canConfirm') is True]
                    # Count automatic successes too: an extra card cannot consume
                    # another allowance for a mutation already committed.
                    completed = {a['id']: a['action'] for a in approvals}
                    completed.update({c['id']: c['action'] for c in cards.values() if c['state'] == 'succeeded'})
                    counts = {}
                    for action in completed.values():
                        kind = KINDS.get(action)
                        if kind:
                            counts[kind] = counts.get(kind, 0) + 1
                    eligible = next((c for c in pending if allowed(c, bounds, counts)), None)
                    if eligible:
                        result = http.checked(await client.post('/api/v1/business-actions/' + eligible['id'] + '/confirm', json={'expectedRevision': eligible['revision']}))
                        kind = KINDS[eligible['action']]
                        counts[kind] = counts.get(kind, 0) + 1
                        approval = {'id': eligible['id'], 'action': eligible['action'], 'authorizedTurn': turn, 'result': result}
                        approvals.append(approval)
                        if progress:
                            progress({'kind': 'approval', **approval})
                        follow(result.get('continuation'))
                        continue
                    for card in pending:
                        if progress:
                            progress({'kind': 'unapproved_pending_action', 'action': card['action'], 'id': card['id'], 'turn': turn, 'reason': 'outside frozen authorized action allowance'})
                    return values[-1], approvals
                await asyncio.sleep(1)

    http.settle = settle
