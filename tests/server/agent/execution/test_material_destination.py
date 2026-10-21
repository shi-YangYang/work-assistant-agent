"""Destination reference checks do not substitute for the semantic judge."""
import pytest

from app.agent.actions.material_selection import MaterialSelection, issue, resolve


def payload(text):
    source = {'deliverableId': 'file', 'revision': 1, 'fileId': 'attachment'}
    return {'messageId': 'current', 'currentUserText': text, 'conversationTask': {},
        'privateDeliverables': {'collectionComplete': True, 'items': [{'files': [{'materialSource': source}]}]},
        'verifiedReads': {'ownWorkRead': [{'id': 'work-a', 'title': '资料整理'}]},
        'proposedOperation': {'action': 'create_work', 'changes': {'materials': [source]}}}


def chosen(request, target, *, quote=None, source='user', **kwargs):
    return MaterialSelection(mode='all', quote=request['currentUserText'],
        destination=target, targetId='work-a' if target == 'existing' else '',
        destinationEvidence={'source': source, 'messageId': request['messageId'],
            'quote': request['currentUserText'] if quote is None else quote}, **kwargs)


@pytest.mark.parametrize('state', ['', 'cancelled', 'needs_input'])
@pytest.mark.parametrize('target', ['existing', 'new'])
@pytest.mark.parametrize('evidence_source', ['user', 'interaction'])
def test_generic_my_work_never_selects_unique_candidate_or_new(state, target, evidence_source):
    request = payload('之前的  都添加到 我的工作  里面')
    if state:
        request['conversationTask']['previousTask'] = {'state': state,
            'userSources': [{'messageId': 'old', 'userText': request['currentUserText']}],
            'items': [{'state': 'proposed', 'action': 'create_work', 'targetId': ''}]}
    request['conversationTask']['interactionAnswers'] = [{'text': request['currentUserText'], 'selected': []}]
    result = resolve(chosen(request, target, source=evidence_source), request, resume=bool(state))
    assert result['destination'] == 'unselected'
    assert result['destinationProof'] == {}
    assert len(result['sources']) == 1
    assert issue(result, request['proposedOperation'], [])['field'] == 'target'


@pytest.mark.parametrize('text', ['放进《资料整理》，保存全部文件', '把文件存到 work-a'])
def test_literal_unique_read_title_or_id_is_reference_evidence(text):
    request = payload(text)
    assert resolve(chosen(request, 'existing'), request)['targetId'] == 'work-a'


@pytest.mark.parametrize('truncated', [False, True])
def test_ambiguous_or_incomplete_read_set_cannot_ground_title(truncated):
    request = payload('放进《资料整理》，保存全部文件')
    if truncated:
        request['verifiedReads']['ownWorkReadTruncated'] = True
    else:
        request['verifiedReads']['ownWorkRead'].append({'id': 'work-b', 'title': '资料整理'})
    assert resolve(chosen(request, 'existing'), request)['destination'] == 'unselected'
    request['currentUserText'] = '放进 work-a，保存全部文件'
    assert resolve(chosen(request, 'existing'), request)['targetId'] == 'work-a'


@pytest.mark.parametrize('text', ['新建一条资料整理工作，把所有文件保存进去', '另建一项工作', '创建工作',
    '新建一条文件整理工作', '新建一项报告归档工作'])
def test_explicit_new_work_reference_is_preserved(text):
    request = payload(text)
    assert resolve(chosen(request, 'new'), request)['destination'] == 'new'


@pytest.mark.parametrize('text', ['新建一个文件放进我的工作', '新建文件夹后把材料放到工作',
    '新建一份报告，保存在工作里', '新建一条资料整理文件', '另建一条目录',
    '新建一份工作报告', '新建文件用于工作'])
def test_creating_other_objects_is_not_a_new_work_destination(text):
    request = payload(text)
    assert resolve(chosen(request, 'new'), request)['destination'] == 'unselected'


def previous_reply(text):
    request = payload('把之前文件都添加到我的工作')
    selected = resolve(MaterialSelection(mode='all', quote=request['currentUserText']), request)
    request.update(messageId='reply', currentUserText=text, materialCollections=[selected])
    value = chosen(request, 'new').model_copy(update={'mode': 'previous', 'previousId': selected['id']})
    return request, value, selected


def test_legacy_collection_supplies_new_work_type_but_never_an_existing_id():
    request, value, _ = previous_reply('另建一条保存就好')
    assert resolve(value, request, resume=True)['destination'] == 'new'
    assert resolve(value, request)['destination'] == 'unselected'
    request['currentUserText'] = '就放现有那条'
    value = chosen(request, 'existing').model_copy(update={'mode': 'previous', 'previousId': value.previousId})
    assert resolve(value, request, resume=True)['destination'] == 'unselected'


def test_excerpt_cannot_hide_other_object_type_in_elliptical_reply():
    request, value, _ = previous_reply('另建一条文件记录')
    value = value.model_copy(update={'destinationEvidence': value.destinationEvidence.model_copy(update={'quote': '另建一条'})})
    assert resolve(value, request, resume=True)['destination'] == 'unselected'


def test_existing_elliptical_reply_requires_current_matching_destination_panel():
    request, value, selected = previous_reply('就放现有那条')
    value = chosen(request, 'existing').model_copy(update={'mode': 'previous', 'previousId': value.previousId})
    question = {'id': 'material-destination-' + selected['id'][:32],
        'options': [{'id': 'work-a', 'objectType': 'work', 'objectId': 'work-a', 'label': '资料整理'},
                    {'id': 'new', 'label': '新建一条工作'}]}
    request['destinationQuestions'] = [question]
    assert resolve(value, request, resume=True)['targetId'] == 'work-a'
    request['destinationQuestions'] = [{**question, 'id': 'material-destination-other'}]
    assert resolve(value, request, resume=True)['destination'] == 'unselected'
    request['destinationQuestions'] = [question, {**question, 'id': 'material-destination-other'}]
    assert resolve(value, request, resume=True)['destination'] == 'unselected'
    request['destinationQuestions'] = [{**question, 'options': [*question['options'],
        {'id': 'work-b', 'objectType': 'work', 'objectId': 'work-b', 'label': '别的工作'}]}]
    assert resolve(value, request, resume=True)['destination'] == 'unselected'


def test_actual_selected_new_work_option_needs_no_model_requoted_label():
    request = payload('这批文件保存到哪里：新建一条工作')
    request['conversationTask']['interactionAnswers'] = [{'text': '', 'selected': [{'id': 'new', 'label': '新建一条工作'}]}]
    value = chosen(request, 'new', source='interaction', quote='')
    assert resolve(value, request)['destination'] == 'new'
    request['conversationTask']['interactionAnswers'][0]['selected'][0]['label'] = '新建文件夹'
    assert resolve(value, request)['destination'] == 'unselected'


@pytest.mark.parametrize('source', ['none', 'user', 'work_reference', 'interaction', 'directive'])
def test_current_reference_locates_same_existing_target_independent_of_model_label(source):
    request = payload('之前生成的这些文件都加到这条工作里，原来的工作内容保留。')
    request['conversationTask']['workReference'] = {'id': 'work-a', 'title': '资料整理'}
    # Identical titles do not weaken the current reference's exact ID.
    request['verifiedReads']['ownWorkRead'].append({'id': 'work-b', 'title': '资料整理'})
    result = resolve(chosen(request, 'existing', source=source), request)
    assert result['targetId'] == 'work-a'
    assert result['destinationProof'] == {'source': 'work_reference',
        'messageId': 'current', 'quote': request['currentUserText']}


@pytest.mark.parametrize('case', ['missing', 'unavailable', 'different-id', 'historical', 'old-quote', 'invalid-quote'])
def test_reference_does_not_replace_missing_invalid_or_historical_target_evidence(case):
    request = payload('把这些文件加到这条工作里')
    request['conversationTask']['workReference'] = {'id': 'work-a', 'title': '资料整理'}
    value = chosen(request, 'existing')
    if case == 'missing':
        request['conversationTask'].pop('workReference')
    elif case == 'unavailable':
        request['conversationTask']['workReference']['unavailable'] = True
    elif case == 'different-id':
        request['conversationTask']['workReference']['id'] = 'work-b'
    elif case == 'historical':
        request['conversationTask']['previousTask'] = {'workReference': request['conversationTask'].pop('workReference')}
    else:
        updates = {'messageId': 'old'} if case == 'old-quote' else {'quote': '不是当前用户原话'}
        request['conversationTask']['previousTask'] = {'userSources': [
            {'messageId': 'old', 'userText': request['currentUserText']}]}
        value = value.model_copy(update={'destinationEvidence': value.destinationEvidence.model_copy(update=updates)})
    result = resolve(value, request, resume=True)
    assert result['destination'] == 'unselected' and result['destinationProof'] == {}


def test_explicit_other_target_still_uses_its_own_user_evidence():
    request = payload('把这些文件加到 work-b')
    request['conversationTask']['workReference'] = {'id': 'work-a', 'title': '资料整理'}
    request['verifiedReads']['ownWorkRead'].append({'id': 'work-b', 'title': '资料整理'})
    value = chosen(request, 'existing').model_copy(update={'targetId': 'work-b'})
    result = resolve(value, request)
    assert result['targetId'] == 'work-b'
    assert result['destinationProof']['source'] == 'user'


@pytest.mark.parametrize('target', ['new', 'unselected'])
def test_current_reference_never_replaces_another_destination_kind(target):
    request = payload('新建一条工作，把这些文件保存进去')
    request['conversationTask']['workReference'] = {'id': 'work-a'}
    result = resolve(chosen(request, target), request)
    assert result['destination'] == target and not result['targetId']


@pytest.mark.parametrize('proof', [{}, {'source': 'receipt', 'receiptId': 'receipt-a'}])
def test_new_current_reference_cannot_retarget_a_locked_collection(proof):
    request = payload('将全部文件存到 work-a')
    selected = resolve(chosen(request, 'existing'), request)
    selected['destinationProof'] = proof
    request.update(messageId='reply', currentUserText='剩下的也加到这条工作')
    request['materialCollections'] = [selected]
    request['conversationTask']['workReference'] = {'id': 'work-b'}
    value = chosen(request, 'existing').model_copy(update={'mode': 'previous',
        'previousId': selected['id'], 'targetId': 'work-b'})
    with pytest.raises(ValueError, match='同一工作'):
        resolve(value, request, resume=True)
