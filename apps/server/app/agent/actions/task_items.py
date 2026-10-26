"""Bind a semantically checked operation to a durable atomic task item."""
from uuid import uuid4
from app.core.digests import digest
from app.agent.actions.task_bindings import STALE_BINDING, recovery_binding_error, recovery_plan_state


def work_scope(proposal):
    """Separate atomic work-record steps without treating prose as identity."""
    changes = proposal.get('changes') or {}
    scopes = set()
    for field in changes:
        if field in ('body', 'bodyEdits'):
            scopes.add('body')
        elif field in ('materials', 'materialIds'):
            scopes.add('materials')
        elif field == 'update':
            value = changes[field] if isinstance(changes[field], dict) else {}
            scopes.add('update:' + str(value.get('action', '')) + ':' + str(value.get('id') or ''))
        elif field == 'removeMaterial':
            value = changes[field] if isinstance(changes[field], dict) else {}
            scopes.add('removeMaterial:' + str(value.get('id') or ''))
        else:
            scopes.add('properties')
    return sorted(scopes)


def reference_error(previous, item_id, proposal, *, corrected=()):
    if not item_id:
        return ''
    item = next((item for item in previous if item['id'] == item_id), None)
    recovery = '仅复用操作和对象均匹配的事项 ID；尚未尝试的剩余动作没有 ID 时留空，由服务端首次分配，不要借用其它事项或猜测 ID。'
    if not item:
        return '事项引用不存在。' + recovery
    if item['action'] != proposal['action'] or item.get('targetId', '') != proposal.get('targetId', ''):
        return f"事项 {item_id} 已对应 {item['action']}《{item.get('label', '')}》（对象 {item.get('targetId', '')}），与本次操作或对象不一致。" + recovery
    original = item.get('attemptedOperation', {})
    receipt_bound = item.get('receiptId') and item.get('state') not in ('failed', 'conflict', 'clarification', 'proposed')
    # The omitted first copy is already an operation identity, not a missing
    # source that a later correction may supply.
    if proposal['action'] == 'create_work' and original.get('copyIndex', 1) != proposal.get('copyIndex', 1):
        return '事项引用对应不同副本，不能代替另一项操作。' + recovery
    for field in ('deliverableReference', 'kind', 'date', 'obligationId', 'sourceTokens', 'sharedAttachmentIds'):
        # A missing source may be supplied while correcting a failed create;
        # a source already bound to another entry may never be replaced.
        if original.get(field) and original[field] != proposal.get(field):
            return '事项引用对应不同来源、报告周期或副本，不能代替另一项操作。' + recovery
    if proposal['action'] == 'update_work' and 'workScope' in item and item['workScope'] != work_scope(proposal) and item_id not in corrected:
        return f"事项 {item_id} 对应不同的工作变更范围，不能用正文、进展或材料的已完成回执代替另一项操作。" + recovery
    if proposal['action'] == 'update_work' and receipt_bound:
        aliases = {'bodyEdits': 'body', 'materialIds': 'materials'}
        original_fields = {aliases.get(name, name) for name in original.get('changes', {})}
        fields = {aliases.get(name, name) for name in proposal.get('changes', {})}
        if not original_fields or original_fields != fields:
            return '事项回执对应不同的实际工作字段，不能代替另一项操作。' + recovery
    if proposal['action'] == 'generate_report' and receipt_bound:
        if 'submitAfter' not in original:
            return '事项回执的报告提交要求无法核对，请先核对原操作回执。' + recovery
        if bool(original['submitAfter']) != bool(proposal.get('submitAfter')):
            return '事项回执对应不同的报告提交要求，不能代替另一项操作。' + recovery
    if proposal['action'] in ('edit_report', 'propose_progress', 'propose_followup') and original.get('changes') and set(original['changes']) != set(proposal.get('changes') or {}):
        return '事项引用对应不同的实际字段，不能代替另一项操作。' + recovery
    recovered = item.get('recoveredSchemaFailure') or {}
    retired = (set(recovered.get('attempts', [])) if proposal['action'] == 'update_work'
               and item.get('state') == 'succeeded' and item.get('receiptId')
               and recovered.get('receiptId') == item['receiptId']
               and item.get('recoveredBy') == item_id else set())
    for attempt in item.get('invalidAttempts', []):
        if digest(attempt) in retired:
            continue  # Exact audited Schema attempts settled by this receipt.
        prior = {key: value for key, value in item.items() if key != 'invalidAttempts'}
        error = reference_error([{**prior, 'attemptedOperation': attempt}], item_id, proposal, corrected=corrected)
        if error:
            return error
    return ''


def recovery_candidates(job, proposal):
    """Expose failed attempts to the existing judge, never infer their identity."""
    failures = {entry.get('taskItemId'): entry for entry in job.result.get('toolOutcomes', [])
                if entry.get('taskItemId') and entry.get('category') in ('invalid_arguments', 'conflict', 'transient_failure', 'missing_info')}
    return [{**item, 'failure': {key: failures[item['id']].get(key) for key in ('category', 'message', 'fields')}}
            for item in job.result.get('taskItems', [])
            if item['id'] in failures and not item.get('receiptId')
            and not reference_error([item], item['id'], proposal)][-16:]


def binding_error(job, binding):
    """Check a call-local authorization proof while holding the job lease."""
    item = next((item for item in job.result.get('taskItems', []) if item['id'] == binding.get('itemId')), None)
    if not item or digest(item) != binding.get('snapshot'):
        return STALE_BINDING
    return recovery_binding_error(job, binding)


async def bind(context, proposal, *, continuing=False, item_id='', new_item=False, source=None, snapshots=None, binding=None):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        current = [dict(item) for item in job.result.get('taskItems', [])]
        previous = [dict(item) for item in job.result.get('taskSnapshot', {}).get('previousTask', {}).get('items', [])] if continuing else []
        observed = {item['id']: digest(item) for item in [*previous, *current]}
        missing = [item for item in [*previous, *current]
                   if item['action'] == 'update_work' and ('workScope' not in item or item.get('receiptId') and not item.get('attemptedOperation', {}).get('changes'))
                   or item['action'] == 'generate_report' and item.get('receiptId') and 'submitAfter' not in item.get('attemptedOperation', {})]
        if missing:
            from app.modules.operations.models import BusinessAction
            from sqlalchemy import select
            receipts = {row.id: row for row in (await db.scalars(select(BusinessAction).where(
                BusinessAction.id.in_([item.get('receiptId', '') for item in missing]),
                BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id))).all()}
            for item in missing:
                receipt = receipts.get(item.get('receiptId'))
                if item['action'] == 'generate_report':
                    if receipt and 'submitAfter' in receipt.result:
                        item['attemptedOperation'] = {**item.get('attemptedOperation', {}), 'submitAfter': bool(receipt.result['submitAfter'])}
                    elif receipt and 'submitAfter' in receipt.params:
                        item['attemptedOperation'] = {**item.get('attemptedOperation', {}), 'submitAfter': bool(receipt.params['submitAfter'])}
                    continue
                item.setdefault('workScope', [])
                changes = {}
                if receipt and receipt.action == 'update_work':
                    if receipt.params.get('targetId') == item.get('targetId'):
                        item['workScope'] = work_scope(receipt.params)
                        changes = receipt.params.get('changes') or {}
                    elif receipt.state == 'succeeded' and receipt.result.get('objectId') == item.get('targetId'):
                        # Successful receipts erase params but retain changed
                        # field names. Do not guess missing subrecord targets.
                        fields = receipt.result.get('satisfiedFields', []) if receipt.result.get('unchanged') else receipt.result.get('changedFields', [])
                        changes = dict.fromkeys(fields)
                        if not {'update', 'removeMaterial'} & set(fields):
                            item['workScope'] = work_scope({'changes': changes})
                if changes and not item.get('attemptedOperation', {}).get('changes'):
                    item['attemptedOperation'] = {**item.get('attemptedOperation', {}), 'changes': changes}
            job.result = {**job.result, 'taskItems': current}
            if continuing:
                snapshot = job.result['taskSnapshot']
                job.result = {**job.result, 'taskSnapshot': {**snapshot, 'previousTask': {**snapshot['previousTask'], 'items': previous}}}
        candidates = list({item['id']: item for item in [*previous, *current]}.values())
        corrected = (binding or {}).get('workRecovery', {}).get('items', {})
        if recovery_binding_error(job, binding or {}):
            return STALE_BINDING
        error = reference_error(candidates, item_id, proposal, corrected=corrected)
        if error:
            return error
        item = next((item for item in candidates if item['id'] == item_id), None) if item_id else None
        if not item:
            item = next((item for item in current if item.get('proposal') == digest(proposal)), None)
        if continuing and not item and not new_item:
            matches = [item for item in previous if item['action'] == proposal['action'] and item.get('targetId', '') == proposal.get('targetId', '')]
            if proposal['action'] == 'update_work':
                if any(not item.get('workScope') or item.get('receiptId') and not item.get('attemptedOperation', {}).get('changes') for item in matches):
                    return '历史事项的工作变更范围无法核对，不能据此重做或视为完成；请先核对原操作回执。'
                matches = [item for item in matches if item['workScope'] == work_scope(proposal)]
            if proposal['action'] == 'generate_report' and any(item.get('receiptId') and 'submitAfter' not in item.get('attemptedOperation', {}) for item in matches):
                return '历史事项的报告提交要求无法核对，不能据此重做或视为完成；请先核对原操作回执。'
            matches = [item for item in matches if not reference_error([item], item['id'], proposal)]
            if len(matches) == 1:
                item = matches[0]
            elif matches:
                return '继续处理时请提供准确 task_item_id，区分已经完成和仍待处理的事项。'
        if item:
            # Compare the actual model input, not a mutable context-wide flag.
            # A prior bind by this call may have updated attemptedOperation.
            expected = (binding['snapshot'] if binding and binding.get('itemId') == item['id']
                        else snapshots.get(item['id']) if snapshots is not None else None)
            if snapshots is not None and observed[item['id']] != expected:
                return STALE_BINDING
            error = reference_error([item], item['id'], proposal, corrected=corrected)
            if error:
                return error
        if not item:
            item = {'id': str(uuid4()), 'action': proposal['action'], 'targetId': proposal.get('targetId', ''),
                    'label': str(proposal.get('target') or proposal.get('changes', {}).get('title') or proposal['action'])[:200], 'state': 'proposed'}
            if proposal['action'] == 'update_work':
                item['workScope'] = work_scope(proposal)
        if (snapshots is not None and proposal['action'] == 'create_work' and not item.get('receiptId')
                and item.get('attemptedOperation') and not item.get('invalidAttempts')):
            # A second invalid call may arrive after this bind but before the
            # receipt. Keep the first failed proposal in that later chain too.
            item = {**item, 'invalidAttempts': [item['attemptedOperation']]}
        if item['id'] in corrected:
            item = {**item, 'invalidAttempts': item.get('invalidAttempts') or [item['attemptedOperation']],
                    'workScope': work_scope(proposal)}
        item = {**item, 'proposal': digest(proposal), 'attemptedOperation': {
            name: proposal[name] for name in ('action', 'targetId', 'changes', 'deliverableReference', 'copyIndex', 'kind', 'date', 'obligationId', 'sourceTokens', 'submitAfter', 'sharedAttachmentIds') if name in proposal}}
        if source:
            item['userSource'] = source
        job.result = {**job.result, 'taskItems': [entry for entry in job.result.get('taskItems', []) if entry['id'] != item['id']] + [item]}
        context.task_item_keys[digest(proposal)] = item['id']
        if binding is not None:
            binding.update(itemId=item['id'], snapshot=digest(item))
            if item['id'] in corrected:
                corrected[item['id']]['snapshot'] = digest(item)
        return ''


async def invalid_attempt(context, arguments):
    """Journal an invalid proposal; association and authorization happen later."""
    from app.tasks.lease import lease
    from app.modules.messages.models import Message
    from app.security.ownership import owned
    from app.agent.context.references.conversation_context import request_text
    proposal = {'action': arguments['action'], 'targetId': arguments.get('target_id', ''),
        'changes': arguments.get('changes') or {}, 'kind': arguments.get('report_kind', 'weekly'),
        'date': arguments.get('report_date', ''), 'obligationId': arguments.get('obligation_id', ''),
        'sourceTokens': sorted(arguments.get('source_tokens') or []), 'submitAfter': bool(arguments.get('submit_after'))}
    if arguments.get('copy_index', 1) > 1:
        proposal['copyIndex'] = arguments['copy_index']
    if arguments.get('shared_attachment_ids'):
        proposal['sharedAttachmentIds'] = sorted(arguments['shared_attachment_ids'])
    if arguments.get('deliverable_id'):
        proposal['deliverableReference'] = {'id': arguments['deliverable_id'],
            'revision': arguments.get('deliverable_revision', 0), 'itemIds': [arguments.get('item_id', '')]}
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        source = {'messageId': message.id, 'userText': request_text(message, job)}
        # A later validation failure may already have a verified binding from
        # this call. Reuse that exact server-bound proposal, never create a
        # second item or trust the tool's supplied task_item_id.
        bound_ids = set(context.task_item_keys.values())
        existing = next((item for item in job.result.get('taskItems', [])
                         if item['id'] in bound_ids and not item.get('receiptId')
                         and item.get('attemptedOperation') == proposal
                         and item.get('userSource') == source), None)
        if existing:
            return existing['id']
        # This is only a claimed continuation, not authorization. Retain every
        # proposal so the existing judge can check the entire claim before a
        # receipt may settle it. Never overwrite the first failed proposal.
        current = job.result.get('taskItems', [])
        item = next((item for item in current if item['id'] == arguments.get('task_item_id')), None)
        if (proposal['action'] in ('create_work', 'update_work') and item and not item.get('receiptId')
                and item.get('userSource') == source
                and not reference_error(current, item['id'], proposal, corrected=[item['id']] if proposal['action'] == 'update_work' else [])):
            attempts = item.get('invalidAttempts') or [item['attemptedOperation']]
            if proposal in attempts:
                return item['id']
            # Overflow stays a separate unresolved item; do not truncate the
            # evidence and later claim that an unseen attempt was recovered.
            if len(attempts) < 8:
                updated = {**item, 'invalidAttempts': [*attempts, proposal]}
                job.result = {**job.result, 'taskItems': [updated if entry['id'] == item['id'] else entry for entry in current]}
                return item['id']
    await bind(context, proposal, source=source)
    item_id = context.task_item_keys[digest(proposal)]
    # Only a pre-authorization Schema error can receive this provenance. A
    # later ValueError, authorization refusal or persisted receipt cannot.
    if proposal['action'] == 'update_work':
        from app.modules.work.records.record_schemas import AgentWorkChanges
        try:
            AgentWorkChanges.model_validate(proposal['changes'])
        except ValueError:
            async with context.sessions.begin() as db:
                job, _ = await lease(db, context)
                items = []
                for item in job.result.get('taskItems', []):
                    if item['id'] == item_id and not item.get('receiptId'):
                        item = {**item, 'schemaFailure': {
                            'sourceRevision': context.source_revision, 'nodeScope': context.node_scope,
                            'documents': dict(context.document_versions),
                            'expectedRevision': arguments.get('expected_revision'),
                            'operation': digest(item['attemptedOperation']),
                            'priorPlans': [recovery_plan_state(job, proposal['targetId'], key) for key in
                                           ('workChangeCandidates', 'workChangeRequirements')
                                           if job.result.get(key, {}).get('targets', {}).get(proposal['targetId'])]}}
                    items.append(item)
                job.result = {**job.result, 'taskItems': items}
    return item_id


def work_recovery(job, proposal, plan, source, context):
    """Prove a Schema correction from independent scope, never the claimed ID."""
    from app.agent.actions.work_change_plan import FIELDS, canonical_field
    required = {name for name in FIELDS if getattr(plan, name).mode != 'preserve'}
    supplied = {canonical_field(name) for name in proposal.get('changes', {})}
    state = recovery_plan_state(job, proposal.get('targetId'))
    if (proposal.get('action') != 'update_work' or not required or supplied != required
            or state.get('messageId') != job.target_id or state.get('version') != 1):
        return {}
    proven = {}
    for item in job.result.get('taskItems', []):
        failure = item.get('schemaFailure') or {}
        original = item.get('attemptedOperation') or {}
        if (not failure or item.get('receiptId') or item.get('state') != 'proposed'
                or item.get('userSource') != source
                or failure.get('sourceRevision') != context.source_revision
                or failure.get('nodeScope') != context.node_scope
                or failure.get('documents') != context.document_versions
                or failure.get('expectedRevision') != proposal.get('expectedRevision')
                or failure.get('operation') != digest(original)):
            continue
        # reference_error checks all hard identities; missing references are
        # also significant here, unlike a create with a missing source.
        references = ('deliverableReference', 'copyIndex', 'kind', 'date', 'obligationId', 'sourceTokens', 'sharedAttachmentIds', 'submitAfter')
        if (reference_error([item], item['id'], proposal, corrected=[item['id']])
                or any(original.get(name) != proposal.get(name) for name in references)):
            continue
        if any(prior.get('scope') != state.get('scope')
               or prior.get('target', {}).get('definitions') != state.get('target', {}).get('definitions')
               for prior in failure.get('priorPlans', [])):
            continue
        attempts = item.get('invalidAttempts') or [original]
        from app.modules.work.records.record_schemas import AgentWorkChanges
        valid_attempt = False
        for attempt in attempts:
            try:
                AgentWorkChanges.model_validate(attempt.get('changes'))
                valid_attempt = True
            except ValueError:
                pass
        if valid_attempt:
            continue
        old_fields = {canonical_field(name) for attempt in attempts for name in attempt.get('changes', {})}
        dropped = old_fields - supplied
        if (not dropped or not required <= old_fields or not old_fields <= set(FIELDS)
                or any(getattr(plan, name).mode != 'preserve' for name in dropped)):
            continue
        outcomes = [entry for entry in job.result.get('toolOutcomes', []) if entry.get('taskItemId') == item['id']]
        if not outcomes or any(entry.get('category') != 'invalid_arguments' or entry.get('receiptId') for entry in outcomes):
            continue
        barriers = {key: value for key, value in job.result.get('taskBarriers', {}).items()
                    if value.get('taskItemId') == item['id']}
        if any(value.get('category') != 'invalid_arguments' for value in barriers.values()):
            continue
        proven[item['id']] = {'snapshot': digest(item), 'attempts': [digest(attempt) for attempt in attempts], 'outcomes': {entry['key']: digest(entry) for entry in outcomes},
                              'barriers': {key: digest(value) for key, value in barriers.items()}}
    return {'items': proven, 'target': proposal['targetId'], 'plan': digest(state),
            'required': sorted(required), 'selectedPlan': digest(recovery_plan_state(job, proposal['targetId'], 'workChangeRequirements'))} if proven else {}


def settle_work_recovery(job, binding, result):
    """Called inside the successful receipt transaction after binding checks."""
    proof = binding.get('workRecovery')
    if (not proof or result.get('state') != 'succeeded' or result.get('action') != 'update_work'
            or result.get('messageId') != job.target_id or result.get('taskItemId') != binding.get('itemId')
            or result.get('objectId') != proof['target'] or not result.get('id')):
        return
    fields = set(result.get('changedFields', []))
    if result.get('unchanged'):
        fields.update(result.get('satisfiedFields', []))
    from app.agent.actions.work_change_plan import canonical_field
    if not set(proof['required']) <= {canonical_field(name) for name in fields}:
        return
    outcomes = [entry for entry in job.result.get('toolOutcomes', [])
                if entry.get('taskItemId') in proof['items']]
    barriers = {key: value for key, value in job.result.get('taskBarriers', {}).items()
                if key in {key for original in proof['items'].values() for key in original['barriers']}}
    items = []
    for item in job.result.get('taskItems', []):
        if item['id'] in proof['items']:
            item = {**item, 'state': 'succeeded', 'receiptId': result['id'], 'recoveredBy': binding['itemId'],
                    'recoveredSchemaFailure': {'plan': proof['plan'], 'receiptId': result['id'],
                                               'attempts': proof['items'][item['id']]['attempts'], 'outcomes': [entry for entry in outcomes if entry.get('taskItemId') == item['id']],
                                               'barriers': {key: value for key, value in barriers.items() if value.get('taskItemId') == item['id']}}}
        items.append(item)
    job.result = {**job.result, 'taskItems': items,
                  'taskBarriers': {key: value for key, value in job.result.get('taskBarriers', {}).items() if key not in barriers}}
