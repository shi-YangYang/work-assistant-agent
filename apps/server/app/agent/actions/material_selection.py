"""The existing authorization judge selects sources; code checks set coverage."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.attachment_limits import MAX_ATTACHMENTS
from app.core.digests import digest
from app.modules.work.records.record_schemas import MaterialSource
from app.tasks.feedback.material_requirements import source_key, uncovered


class DestinationEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: Literal['none', 'user', 'work_reference', 'interaction', 'directive'] = 'none'
    messageId: str = ''
    quote: str = Field(default='', max_length=2000)


class MaterialSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['none', 'all', 'selected', 'previous'] = 'none'
    quote: str = Field(default='', max_length=2000)
    messageId: str = ''
    references: list[MaterialSource] = Field(default_factory=list, max_length=200)
    previousId: str = ''
    destination: Literal['unselected', 'existing', 'new'] = 'unselected'
    targetId: str = ''
    destinationEvidence: DestinationEvidence = Field(default_factory=DestinationEvidence)


def normalize_contract(raw, request):
    """Decode equivalent wire spellings, without manufacturing a verdict.

    Keep the advertised schema strict. Only the current server-validated work
    reference may fill a missing ID explicitly described as that reference.
    Proposal IDs, search results and previous task targets are never fallbacks.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get('materialSelection'), dict):
        return raw
    value = dict(raw['materialSelection'])
    evidence = value.get('destinationEvidence', {})
    if not isinstance(evidence, dict):
        return raw  # The typed contract reports this invalid structure.
    evidence = dict(evidence)

    def alias(record, alternate, canonical):
        if alternate in record:
            if canonical in record and record[canonical] != record[alternate]:
                raise ValueError('材料选择包含互相冲突的字段别名。')
            record[canonical] = record.pop(alternate)

    alias(value, 'selection', 'mode')
    alias(value, 'quoteMessageId', 'messageId')
    alias(evidence, 'quoteMessageId', 'messageId')
    reference_destination = value.get('destination') == 'work_reference'
    moved_target = 'targetId' in evidence
    if reference_destination:
        if evidence.get('source') != 'work_reference':
            raise ValueError('工作引用目标与其证据来源不一致。')
        value['destination'] = 'existing'
    if 'targetId' in evidence:
        if evidence.get('source') != 'work_reference' or value.get('destination') != 'existing':
            raise ValueError('材料目标证据不能替代所选目标类型。')
        if 'targetId' in value and value['targetId'] != evidence['targetId']:
            raise ValueError('材料选择包含互相冲突的目标 ID。')
        value['targetId'] = evidence.pop('targetId')
    uses_reference = value.get('destination') == 'existing' and evidence.get('source') == 'work_reference'
    needs_reference = uses_reference and (reference_destination or moved_target
        or 'targetId' not in value or value['targetId'] == '')
    if needs_reference:
        reference = request['conversationTask'].get('workReference') or {}
        identifier = reference.get('id')
        if not identifier or reference.get('unavailable'):
            raise ValueError('本条消息没有可用的工作引用。')
        for source in (value, evidence):
            if source.get('messageId') not in (None, '', request['messageId']):
                raise ValueError('历史选择不能借用本条消息的工作引用。')
            quote = source.get('quote', '')
            if not isinstance(quote, str) or quote and (not quote.strip() or quote not in request['currentUserText']):
                raise ValueError('工作引用的选择原话必须来自当前消息。')
        if value.get('targetId') not in (None, '', identifier):
            raise ValueError('所选工作与本条消息的工作引用不一致。')
        # Explicit nulls remain invalid under the typed contract; only an
        # omitted/default-empty identifier is a recoverable reference shorthand.
        if 'targetId' not in value or value['targetId'] == '':
            value['targetId'] = identifier
    # Complete canonical evidence is checked by destination(), which can keep
    # valid sources while conservatively asking for an unproven destination.
    value['destinationEvidence'] = evidence
    return {**raw, 'materialSelection': value}


POLICY = '''materialSelection 独立解析用户所选文件：none=不保存；all=privateDeliverables 完整目录的全部可用文件，不逐个抄 references；selected=明确选定的稳定来源及版本；previous=续接 previousId 的集合。quote/messageId 引用材料选择原话，不能从提案或旧失败操作反推范围。destination 单独解析为 unselected/existing/new：destinationEvidence.source=user 时引用明确选择已有目标或新建的用户原话及 messageId；work_reference 用本条已验证工作引用；interaction 用实际选择的对象或答案原话；directive 用已绑定目标的持续指令及 messageId。previous 已验证目标可直接沿用；从未选变为已选须有新的目标证据，重复原句不是回答。没有目标证据就 unselected，只问位置、不重问文件。“我的工作”、查到唯一工作、旧失败 create_work 都不是选择新建或已有目标。'''


def proposed_sources(proposal):
    changes = proposal.get('changes') or {}
    return [*changes.get('materials', []), *changes.get('update', {}).get('materials', []),
            *({'attachmentId': value} for value in proposal.get('sharedAttachmentIds', []))]


def fresh_choice(text, identifier, request, selected):
    previous = request['conversationTask'].get('previousTask', {})
    unresolved = bool(selected and selected['destination'] == 'unselected')
    unresolved = unresolved or any(item.get('destination') == 'unselected' for item in request.get('materialCollections', []))
    # Legacy pending requests have no destination contract. Their failed
    # action/label cannot upgrade the same unanswered words to a selection.
    unresolved = unresolved or previous.get('state') == 'needs_input' and any(
        item.get('action') in ('create_work', 'update_work') and not item.get('targetId')
        and item.get('state') not in ('succeeded', 'pending', 'running') for item in previous.get('items', []))
    if not unresolved:
        return True
    old_texts = [item['userText'] for item in previous.get('userSources', [])]
    if selected:
        old_texts.append(selected['quote'])
    old_texts.extend(item['quote'] for item in request.get('materialCollections', []) if item.get('destination') == 'unselected')
    unchanged = any(''.join(text.split()) == ''.join(old.split()) for old in old_texts)
    return identifier == request['messageId'] and not unchanged


async def destination_questions(db, actor, job, message, request):
    """Read actual destination panels for grounding, never select or settle one."""
    identifier = job.result.get('continuation', {}).get('interactionId') or job.result.get('questionCandidate')
    if not identifier:
        return []
    from app.modules.interactions.models import AssistantInteraction
    from app.modules.interactions.queries import validate
    from app.security.ownership import owned
    row = await owned(db, AssistantInteraction, identifier, actor)
    task = request['conversationTask']
    if row.conversation_id != message.conversation_id or row.task_id not in {
            task.get('taskId'), task.get('previousTask', {}).get('id')}:
        return []
    if row.state != 'waiting' and not (row.state == 'answered' and row.continuation.get('messageId') == message.id):
        return []
    collections = [*request.get('materialCollections', []),
                   *task.get('previousTask', {}).get('materialCollections', [])]
    question_ids = {'material-destination-' + item['id'][:32] for item in collections}
    questions = [{'id': question['id'], 'options': question['options']}
                 for question in row.questions if question['id'] in question_ids]
    if questions:
        await validate(db, actor, row)
    return questions


def grounded_target(value, quote, request, *, selected=None, resume=False, answer_text=''):
    """Reference evidence only: a match cannot authorize an operation."""
    reads = request.get('verifiedReads', {})
    works = reads.get('ownWorkRead', [])
    if value.destination == 'existing':
        matches = {item['id'] for item in works if re.search(
            r'(?<![\w-])' + re.escape(item['id']) + r'(?![\w-])', quote)}
        if matches:
            return matches == {value.targetId}
        if not reads.get('ownWorkReadTruncated'):
            matches = {item['id'] for item in works
                       if item.get('title') and item['title'] not in ('工作', '我的工作') and item['title'] in quote}
            if matches:
                return matches == {value.targetId}
    else:
        # Keep the object explicit. Creating a file/folder/report then saving
        # it to My Work does not specify a new work record.
        for match in re.finditer(r'(?:新建|另建|新增|创建|建立)\s*(?:一|1)?\s*(?:条|项|个)?\s*([^，。！？；\n]{0,40}?)工作(?!报告|计划|说明|文件|文档|目录|表格|清单|记录|流|区|簿|表)', quote):
            if not re.search(r'保存|添加|放(?:到|进|在)|存(?:到|进|在)|后|再|并|用于|用来|到我的', match.group(1)):
                return True
    # Elliptical replies must be the actual answer, not a short excerpt that
    # omits a following noun such as "file" or "folder".
    text = re.sub(r'[\s，。！？、,.!?]', '', answer_text)
    new_work_reply = value.destination == 'new' and bool(re.fullmatch(
        r'(?:就)?(?:另建|新建|另开)(?:一|1)?(?:条|项|个)(?:保存(?:这些文件|这些材料|文件|材料)?)?(?:吧|就好|就行)?', text))
    # A persisted work-material collection supplies the omitted object type,
    # even for an older plain-text question. It supplies no existing work ID.
    if new_work_reply and resume and selected and selected['destination'] == 'unselected':
        return True
    questions = request.get('destinationQuestions', []) if resume else []
    if len(questions) != 1:
        return False
    if selected:
        questions = [item for item in questions if item['id'] == 'material-destination-' + selected['id'][:32]]
    if len(questions) != 1:
        return False
    options = questions[0]['options']
    if value.destination == 'existing':
        choices = {item['objectId'] for item in options if item.get('objectType') == 'work' and item.get('objectId')}
        return choices == {value.targetId} and bool(re.fullmatch(
            r'(?:就)?(?:放(?:到|进)?|保存到|存到|加到|添加到)?(?:现有|已有)(?:的)?(?:那|这)?(?:一)?(?:条|项|个)(?:工作)?(?:里|里面)?(?:吧|就好|就行)?', text))
    return new_work_reply and any(item['id'] == 'new' and not item.get('objectId') and item['label'] == '新建一条工作' for item in options)


def destination(value, request, *, selected=None, resume=False):
    """Check provenance and target reference; intent still belongs to the judge."""
    empty = {'destination': 'unselected', 'targetId': '', 'destinationProof': {}}
    if value.destination == 'existing' and not value.targetId or value.destination != 'existing' and value.targetId:
        raise ValueError('材料目标类型与 targetId 不一致。')
    if selected and selected.get('targetId') and not selected.get('destinationProof'):
        receipt = next((card for card in request.get('completedOrPendingSteps', [])
            if card.get('state') == 'succeeded' and card.get('objectId') == selected['targetId']
            and card.get('action') in ('create_work', 'update_work')
            and card.get('taskItemId') in selected.get('taskItemIds', [])), None)
        if receipt:
            selected = {**selected, 'destinationProof': {'source': 'receipt', 'receiptId': receipt['id']}}
    if selected and selected.get('destinationProof'):
        # This is the same persisted collection, not an overlapping file set.
        if value.destination == 'unselected' and value.destinationEvidence.source == 'none':
            return {key: selected[key] for key in empty}
        if value.destination != selected['destination'] or value.targetId != selected.get('targetId', ''):
            raise ValueError('已有选择或写入回执绑定了保存目标，剩余材料只能续存到同一工作。')
        return {key: selected[key] for key in empty}
    if selected and selected.get('targetId') and (value.destination != 'existing' or value.targetId != selected['targetId']):
        raise ValueError('已有选择或写入回执绑定了保存目标，剩余材料只能续存到同一工作。')
    if value.destination == 'unselected':
        return empty
    evidence = value.destinationEvidence
    task = request['conversationTask']
    reference = task.get('workReference') or {}
    # This projection is the current message's server-validated reference,
    # independent of the judge's provenance label. It locates an existing
    # target; the same semantic authorization still decides whether to write.
    current_evidence = (not evidence.messageId or evidence.messageId == request['messageId']) and (
        not evidence.quote or bool(evidence.quote.strip()) and evidence.quote in request['currentUserText'])
    if (value.destination == 'existing' and reference.get('id') == value.targetId
            and not reference.get('unavailable') and current_evidence):
        quote = evidence.quote
        if not quote and (not value.messageId or value.messageId == request['messageId']):
            quote = value.quote if value.quote in request['currentUserText'] else ''
        return {'destination': 'existing', 'targetId': value.targetId,
                'destinationProof': {'source': 'work_reference', 'messageId': request['messageId'], 'quote': quote}}
    proven = False
    if evidence.source == 'interaction':
        for answer in task.get('interactionAnswers', []):
            choices = answer.get('selected', [])
            if value.destination == 'existing' and any(option.get('objectType') == 'work' and option.get('objectId') == value.targetId for option in choices):
                proven = True
            if value.destination == 'new' and any(not option.get('objectId') and grounded_target(
                    value, option['label'], request) for option in choices):
                proven = True
            # A selected object is explicit. Free text and non-object choices
            # must identify this destination as well as quote an actual answer.
            texts = [answer.get('text', ''), *(option['label'] for option in choices if not option.get('objectId'))]
            if evidence.quote.strip() and any(evidence.quote in text and fresh_choice(text, request['messageId'], request, selected)
                    and grounded_target(value, evidence.quote, request, selected=selected, resume=resume, answer_text=text) for text in texts):
                proven = True
    elif evidence.source == 'directive':
        proven = value.destination == 'existing' and any(
            item['messageId'] == evidence.messageId and item.get('targetId') == value.targetId
            for item in task.get('activeDirectives', []))
    elif evidence.source == 'user':
        identifier = evidence.messageId or request['messageId']
        sources = [{'messageId': request['messageId'], 'userText': request['currentUserText']}]
        if resume:
            sources.extend(task.get('previousTask', {}).get('userSources', []))
        source = next((item for item in sources if item['messageId'] == identifier), None)
        proven = bool(source and evidence.quote.strip() and evidence.quote in source['userText'])
        if proven:
            proven = fresh_choice(source['userText'], identifier, request, selected) and grounded_target(
                value, evidence.quote, request, selected=selected, resume=resume and identifier == request['messageId'],
                answer_text=source['userText'])
    if not proven:
        return empty
    return {'destination': value.destination, 'targetId': value.targetId,
            'destinationProof': {**evidence.model_dump(), 'messageId': evidence.messageId or request['messageId']}}


def resolve(value, request, *, resume=False, require=True):
    """No selection is inferred from names, proposals or catalogue membership."""
    if value.mode == 'none':
        if require and proposed_sources(request['proposedOperation']):
            raise ValueError('写入材料时必须独立解析 materialSelection，不能为 none。')
        return None
    previous = list(request.get('materialCollections', []))
    if resume:
        previous.extend(request['conversationTask'].get('previousTask', {}).get('materialCollections', []))
    if value.mode == 'previous':
        selected = next((item for item in previous if item['id'] == value.previousId), None)
        if not selected:
            raise ValueError('previousId 必须是已解析集合的准确 ID。')
        target = destination(value, request, selected=selected, resume=resume)
        return {**selected, **target, 'continued': True}
    sources = [{'messageId': request['messageId'], 'userText': request['currentUserText']}]
    task = request['conversationTask']
    sources.extend({'messageId': item['messageId'], 'userText': item['quote']} for item in task.get('activeDirectives', []))
    if resume:
        sources.extend(task.get('previousTask', {}).get('userSources', []))
    identifier = value.messageId or request['messageId']
    if not value.quote.strip() or not any(item['messageId'] == identifier and value.quote in item.get('userText', '') for item in sources):
        raise ValueError('材料选择必须引用当前或有效承接的真实用户原话。')
    if value.mode == 'all':
        catalog = request['privateDeliverables']
        if not catalog.get('collectionComplete'):
            raise ValueError('目录尚未完整，不能把当前一页当成全部材料。')
        selected = [file['materialSource'] for item in catalog['items'] for file in item['files']]
    else:
        selected = [source.model_dump(exclude_none=True) for source in value.references]
    if not selected or len({source_key(source) for source in selected}) != len(selected):
        raise ValueError('材料选择必须包含不重复的稳定来源，不能用文件名去重。')
    target = destination(value, request, resume=resume)
    key = digest({'message': identifier, 'quote': value.quote, 'target': target['targetId'],
                  'destination': target['destination']})
    prior = next((item for item in previous if item['id'] == key), None)
    if prior and {source_key(source) for source in prior['sources']} != {source_key(source) for source in selected}:
        raise ValueError('同一原始选择的集合已解析，修正提案不能缩小或扩大该集合；续接使用 previousId。')
    return {'id': key,
            'sourceMessageId': identifier, 'quote': value.quote, 'sources': selected,
            **target, 'taskItemIds': []}


async def validate_sources(db, actor, selection, conversation_id):
    from app.core.errors import problem
    from app.modules.attachments.documents import visible_attachment
    from app.modules.deliverables.queries import get_deliverable
    from app.modules.messages.models import Message
    for source in selection['sources']:
        if source.get('attachmentId'):
            attachment = await visible_attachment(db, source['attachmentId'], actor)
            if attachment.owner_id != actor.id:
                problem(403, '只能选择本人材料')
            if attachment.message_id:
                message = await db.get(Message, attachment.message_id)
                if not message or message.conversation_id != conversation_id:
                    problem(403, '所选材料不属于当前会话')
        else:
            _, record = await get_deliverable(db, actor, source['deliverableId'], source['revision'], conversation_id=conversation_id)
            if not any(file['id'] == source['fileId'] for file in record.files):
                problem(404, '所选成果文件不存在')


def issue(selection, proposal, cards, *, existing_sources=()):
    if not selection:
        return None
    if selection['destination'] == 'unselected':
        return {'kind': 'missing_info', 'field': 'target', 'question': '这些材料要放到哪项工作，还是新建一项工作？'}
    action = proposal.get('operation', proposal.get('action'))
    if (selection['destination'] == 'new' and action != 'create_work'
            or selection['destination'] == 'existing' and (action != 'update_work' or selection['targetId'] != proposal.get('targetId'))):
        return {'kind': 'invalid_arguments', 'field': 'target', 'code': 'target_mismatch'}
    missing = uncovered(selection, cards)
    wanted = {source_key(source) for source in missing}
    supplied = {source_key(source) for source in [*proposed_sources(proposal), *existing_sources]}
    all_selected = {source_key(source) for source in selection['sources']}
    # Small collections are one atomic binding. Larger collections may use the
    # existing per-write limit, with subsequent batches covering the remainder.
    if supplied - all_selected or len(supplied & wanted) < min(len(wanted), MAX_ATTACHMENTS):
        return {'kind': 'invalid_arguments', 'field': 'materials', 'code': 'selection_incomplete',
                'missingMaterials': [source for source in missing if source_key(source) not in supplied],
                'unexpectedMaterials': [source for source in proposed_sources(proposal) if source_key(source) not in all_selected]}
    return None
