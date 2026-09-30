"""Controlled graph/receipt regressions, not a semantic evaluation of a real model."""
import json
from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sqlalchemy import select

from app.agent.prompts.evidence import CLAIM_SUPPORT_POLICY, EVIDENCE_POLICY
from app.modules.executions.models import SandboxExecution
from fakes import completion
from test_response_delivery import RoutingModel, run

pytestmark = pytest.mark.asyncio


class EvidenceModel(RoutingModel):
    experiment: bool = False
    evidence: list = Field(default_factory=list)
    review_inputs: list = Field(default_factory=list)

    async def ainvoke(self, messages, *args, **kwargs):
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            payload = {}
        if payload.get('task') == 'business_reply_review':
            assert CLAIM_SUPPORT_POLICY in messages[0].content
            self.review_inputs.append(payload)
        return await super().ainvoke(messages, *args, **kwargs)

    async def _agenerate(self, messages, *args, **kwargs):
        self.calls += 1
        system = '\n'.join(str(message.content) for message in messages if isinstance(message, SystemMessage))
        assert system.count(EVIDENCE_POLICY) == 1
        names = [tool['function']['name'] for tool in kwargs.get('tools', [])]
        self.requests.append(names)
        if self.experiment and self.calls == 1 and 'run_python' in names:
            answer = AIMessage(content='', tool_calls=[{'id': 'experiment', 'name': 'run_python', 'args': {
                'code': 'import platform\nprint(platform.python_version())\nprint(sorted({"b", "a"}))',
                'title': '观察当前环境下的排序结果'}}])
        else:
            if self.experiment:
                result = next((json.loads(message.content) for message in reversed(messages)
                               if isinstance(message, ToolMessage) and message.name == 'run_python'), None)
                if result is not None:
                    self.evidence.append(result)
                if result and result['state'] == 'succeeded':
                    self.answer = '本次环境及输出：\n' + result['stdout'] + '\n只说明本次输入下的观察。'
                else:
                    self.answer = '本次未完成实测：' + (result['stderr'] if result else '执行服务未启用。')
                    self.task = {'state': 'blocked', 'remaining': ['实测尚未完成']}
            answer = completion(self.answer, task=self.task, verification_requested=self.verification_requested,
                                verification_quote=self.verification_quote)
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.mark.parametrize('user_text,answer', [
    ('什么是递归？简单说明即可。', '递归是在解决问题时调用自身，并通过结束条件停止。'),
    ('把“欢迎回来”翻译成英文。', 'Welcome back.'),
    ('解释这段代码，不需要运行：name.strip()。', '它返回去掉字符串两端空白的结果。'),
])
async def test_ordinary_tasks_still_finish_in_one_call_with_sandbox_available(setup, user_text, answer):
    settings = replace(setup[0], sandbox_url='http://sandbox.invalid', sandbox_token='controlled')
    fake = EvidenceModel(model='controlled', api_key='unused', answer=answer)
    result, stored = await run((settings, *setup[1:]), fake, user_text)
    assert result['reply'] == answer and result['job']['taskOutcome']['state'] == 'completed'
    assert fake.calls == 1 and fake.reviews == 0 and 'run_python' in fake.requests[0]
    assert not any(node['kind'] in ('tool', 'review') for node in result['job']['nodes'])
    assert not stored.get('replyReview') and not stored.get('deliveryRepairs')
    assert not result['actions'] and not result['drafts'] and not result['deliverables']


@pytest.mark.parametrize('enabled,succeeds,verify', [
    (True, True, False), (True, True, True), (True, False, False), (False, False, False),
])
async def test_experiment_receipt_and_unavailable_paths_use_existing_graph_without_extra_gate(setup, monkeypatch, enabled, succeeds, verify):
    submissions = []
    observed = 'controlled-test-runtime\n[\'a\', \'b\']'

    class ObservationClient:
        def __init__(self, settings):
            assert enabled

        async def read(self, key):
            return None

        async def submit(self, body):
            submissions.append(body)
            return {'state': 'succeeded' if succeeds else 'failed', 'exitCode': 0 if succeeds else 1,
                    'stdout': observed if succeeds else '', 'stderr': '' if succeeds else 'RuntimeError: controlled failure', 'files': []}

        async def best_effort(self, operation, key):
            assert operation == 'release'

    monkeypatch.setattr('app.modules.executions.service.SandboxClient', ObservationClient)
    settings = replace(setup[0], sandbox_url='http://sandbox.invalid' if enabled else '', sandbox_token='controlled' if enabled else '')
    quote = '核验“排序总会报错”的说法' if verify else ''
    fake = EvidenceModel(model='controlled', api_key='unused', experiment=True,
                         verification_requested=verify, verification_quote=quote)
    result, stored = await run((settings, *setup[1:]), fake, (quote + '，' if quote else '') + '请做一个最小实验，观察集合排序。')
    assert ('run_python' in fake.requests[0]) is enabled
    assert fake.calls == (2 if enabled else 1) and fake.reviews == int(verify)
    assert len(submissions) == int(enabled) and len(fake.evidence) == int(enabled)
    assert sum(node['kind'] == 'tool' for node in result['job']['nodes']) == int(enabled)
    assert sum(node['kind'] == 'review' for node in result['job']['nodes']) == int(verify)
    assert not stored.get('deliveryRepairs')
    assert not result['actions'] and not result['drafts'] and not result['deliverables']
    async with setup[1]() as db:
        receipts = list((await db.scalars(select(SandboxExecution).where(SandboxExecution.job_id == result['job']['id']))).all())
        assert len(receipts) == int(enabled)
        if enabled:
            assert receipts[0].result == fake.evidence[0]
            assert receipts[0].code == submissions[0]['code']
            assert receipts[0].state == ('succeeded' if succeeds else 'failed')
    if succeeds:
        assert observed in result['reply'] and result['job']['taskOutcome']['state'] == 'completed'
    else:
        assert observed not in result['reply'] and '未完成实测' in result['reply']
        assert result['job']['taskOutcome']['state'] == 'blocked'
    if verify:
        actual = [row for row in fake.review_inputs[0]['toolEvidence'] if row['tool'] == 'run_python']
        assert len(actual) == 1 and json.loads(actual[0]['result']) == fake.evidence[0]
        assert fake.review_inputs[0]['reviewScope'] == 'facts_only'
        assert 'currentActions' not in fake.review_inputs[0]
        assert fake.review_inputs[0]['verificationQuote'] == quote


class QuoteRepairModel(EvidenceModel):
    corrected_verification: bool | None = None

    async def _agenerate(self, messages, *args, **kwargs):
        result = await super()._agenerate(messages, *args, **kwargs)
        call = result.generations[0].message.tool_calls[0]
        if call['name'] == 'finish_task':
            repaired = self.calls > 2 and self.corrected_verification is not None
            call['args']['verification_requested'] = self.corrected_verification if repaired else True
            call['args']['verification_quote'] = ('核验这个排序结论' if self.corrected_verification else '') if repaired else '此前用户说过的另一个主张'
        return result


@pytest.mark.parametrize('corrected_verification', [False, True, None])
async def test_current_verification_quote_is_repaired_once_without_reexecuting_experiment(setup, monkeypatch, corrected_verification):
    submissions = []

    class Client:
        def __init__(self, settings):
            pass

        async def read(self, key):
            return None

        async def submit(self, body):
            submissions.append(body)
            return {'state': 'succeeded', 'exitCode': 0, 'stdout': "controlled-test-runtime\n['a', 'b']", 'stderr': '', 'files': []}

        async def best_effort(self, operation, key):
            assert operation == 'release'

    monkeypatch.setattr('app.modules.executions.service.SandboxClient', Client)
    settings = replace(setup[0], sandbox_url='http://sandbox.invalid', sandbox_token='controlled')
    fake = QuoteRepairModel(model='controlled', api_key='unused', experiment=True, corrected_verification=corrected_verification)
    prompt = '请核验这个排序结论' if corrected_verification else '做一个最小排序实验，说明环境'
    result, stored = await run((settings, *setup[1:]), fake, prompt)
    assert len(submissions) == 1 and fake.calls == 3
    assert fake.requests[-1] == ['finish_task']
    assert stored['deliveryRepairs'] == ['protocol']
    assert fake.reviews == int(corrected_verification is True)
    if corrected_verification is None:
        # Controlled models do not reserve an external request; the existing
        # handler uses failed here (real provider calls use awaiting_retry).
        assert result['job']['state'] == 'failed'
        assert '有效收尾' in result['job']['error']
        assert 'controlled-test-runtime' not in result['reply']
    else:
        assert result['job']['taskOutcome']['state'] == 'completed'
        assert 'controlled-test-runtime' in result['reply']
    assert not result['actions'] and not result['drafts']
