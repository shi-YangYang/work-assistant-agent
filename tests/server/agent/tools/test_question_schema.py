"""The model-visible question contract matches the single-choice panel."""
import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from app.agent.tools.control.questions import request_user_input
from app.modules.interactions.schemas import AnswerRequest, Question
from app.modules.interactions.service import checked_answers


def choice(**changes):
    return {'id': 'scope', 'prompt': '优先处理哪个方向？', 'type': 'single',
            'options': [{'id': 'plan', 'label': '实施计划'}, {'id': 'risk', 'label': '风险说明'}], **changes}


def validate(questions):
    return request_user_input.tool_call_schema.model_validate({'questions': questions})


def test_model_schema_exposes_question_limits_single_choice_and_custom_answers():
    parameters = convert_to_openai_tool(request_user_input)['function']['parameters']
    questions = parameters['properties']['questions']
    assert (questions['minItems'], questions['maxItems']) == (1, 5)
    fields = questions['items']['properties']
    assert fields['type']['enum'] == ['single', 'text']
    assert fields['options']['maxItems'] == 5
    assert fields['allowCustom']['const'] is True
    assert fields['options']['items']['required'] == ['id', 'label']
    assert 'runtime' not in parameters['properties']


@pytest.mark.parametrize('count,option_count', [(1, 1), (5, 5)])
def test_supported_boundaries_preserve_ai_supplied_labels(count, option_count):
    options = [{'id': str(i), 'label': f'方向 {i}'} for i in range(option_count)]
    parsed = validate([choice(id=str(i), options=options) for i in range(count)])
    assert len(parsed.questions) == count
    assert parsed.questions[0].options[0].label == '方向 0'
    assert all(question.allowCustom for question in parsed.questions)


@pytest.mark.parametrize('questions', [
    [],
    [choice(id=str(i)) for i in range(6)],
    [choice(type='multiple')],
    [choice(allowCustom=False)],
    [choice(type='text')],
    [choice(options=[])],
    [choice(options=[{'id': str(i), 'label': str(i)} for i in range(6)])],
    [choice(options=[{'id': 'same', 'label': label} for label in ('计划', '风险')])],
])
def test_invalid_question_combinations_are_rejected_before_tool_execution(questions):
    with pytest.raises(ValidationError):
        validate(questions)


def test_text_only_questions_and_historical_multiple_choice_records_remain_readable():
    parsed = validate([{'id': 'date', 'prompt': '截止日期？', 'type': 'text'}])
    assert parsed.questions[0].options == [] and parsed.questions[0].allowCustom
    assert Question.model_validate(choice(type='multiple')).type == 'multiple'


def test_five_answers_are_accepted_together_but_six_are_rejected():
    questions = [choice(id=str(i)) for i in range(5)]
    answers = [{'questionId': q['id'], 'optionIds': ['plan']} for q in questions]
    body = AnswerRequest(expectedRevision=1, answers=answers)
    result, _ = checked_answers(questions, body.answers)
    assert len(result) == 5 and result[-1]['questionId'] == '4'
    with pytest.raises(ValidationError):
        AnswerRequest(expectedRevision=1, answers=[*answers, {'questionId': '5', 'text': '其他'}])
