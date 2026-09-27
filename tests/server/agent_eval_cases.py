"""Manual live-model evaluations. Each case starts with its own business data.

The matrix varies business vocabulary as well as 35 distinct intentions. Oracles
check persisted effects, unchanged fields, confirmations and useful chat output;
they never accept the assistant's claim of success as proof of a write.
"""
from dataclasses import dataclass, field
from agent_eval_grading import SEMANTIC_RULES


@dataclass
class Case:
    id: str
    turns: list[str]
    rule: str
    seeds: list[dict] = field(default_factory=list)
    role: str = 'employee'
    expected: dict = field(default_factory=dict)
    persona_id: str | None = None
    retry: bool = False


DOMAINS = ['客户回访', '产品调研', '招聘面试', '合同审核', '数据清洗', '活动筹备', '接口联调', '仓库盘点']


def cases():
    result = []
    for index, title in enumerate(DOMAINS, 1):
        other = title + '复盘'
        seed = dict(title=title, summary='已有说明，请保留', status='in_progress', blocker='等待资料', nextStep='核对清单', dueDate='2026-12-20')
        def add(name, text, rule, seeds=None, role='employee', **expected):
            result.append(Case(f'{name}-{index:02}', text if isinstance(text, list) else [text], rule, seeds or [], role, expected))
        add('delegated', f'帮我随机生成一份{title}方面的工作，内容你来安排。', 'creative')
        add('open_ended', ['帮我随机生成一份工作', '给我安排个能马上开始的小任务，具体做什么你决定，放到我的工作里', '随便帮我建个工作，主题你选', '我的工作里放一项你自己设计的任务吧', '帮我想个事情来做，直接保存到我的工作', '你来拟一份工作并新建，不用再问我要内容', '给我随机创建个工作，内容自由发挥', '帮我生成一条可执行的工作事项并保存'][index-1], 'creative')
        add('title_only', f'新建工作，标题“{title}”，其它字段都不要填，状态用默认的。', 'exact_create', title=title, summary='', nextStep='', blocker='', status='in_progress')
        add('explicit_create', f'帮我建工作：{title}。说明写“先核对需求”，下一步写“整理清单”，截止2026年12月20日，进行中。', 'exact_create', title=title, summary='先核对需求', nextStep='整理清单', dueDate='2026-12-20', status='in_progress')
        add('two_creates', f'新建两项工作，一项叫“{title}”，另一项叫“{other}”，都保持进行中。', 'titles', titles=[title, other])
        add('same_title', f'创建两项都叫“{title}”的不同工作，第一项说明写“甲客户”，第二项说明写“乙客户”，不要合并。', 'same_titles', title=title)
        add('rename', f'把我的“{title}”改名为“{other}”，其余不动。', 'patch', [seed], title=other)
        add('complete', f'“{title}”整个事情已经做完了，请在我的工作中标为完成，其它信息保留。', 'patch', [seed], status='done')
        add('block', f'更新“{title}”，状态设为受阻，阻碍改为“等待客户确认”，其他字段不变。', 'patch', [seed], status='blocked', blocker='等待客户确认')
        add('clear_date', f'取消“{title}”的截止日期，别动其他内容。', 'patch', [seed], dueDate=None)
        add('clear_blocker', f'把“{title}”的阻碍清空，其他不变。', 'patch', [seed], blocker='')
        add('rewrite_next', f'帮我给“{title}”拟一个可执行的下一步并保存，只改下一步，别动其它字段。', 'creative_patch', [seed])
        add('multi_turn', [f'创建一项工作，名称“{title}”，说明写“核对需求”。', '把刚才那项工作的下一步改成“整理清单”，其他不动。'], 'exact_create', title=title, summary='核对需求', nextStep='整理清单', status='in_progress')
        add('multi_update', f'把“{title}”改为已完成，同时把“{other}”的下一步改成“整理清单”。', 'multi_patch', [seed, dict(title=other, summary='保留复盘', status='in_progress')], title=title, other=other)
        add('conditional', f'先查“{title}”，如果还是进行中，就将其下一步改为“整理清单”；其他字段保留。', 'patch', [seed], nextStep='整理清单')
        add('delete_confirm', f'删除“{title}”，先给我看确认卡。', 'confirmation', [seed], action='delete_work')
        add('negation', f'不要创建工作。我只是想讨论一下{title}怎么做，先给我三个建议。', 'chat')
        add('quotation', f'客户原话：“创建{title}工作并标为完成”。只是让你解释这句话，不要执行。', 'chat')
        add('fiction_report', f'写一份虚构的{title}日报样例，只在聊天里展示，不保存，不代表我真的完成了。', 'fiction')
        add('random_report', f'随便帮我生成一份{title}报告，内容你自由发挥就行。', 'fiction')
        add('plan_in_chat', f'帮我设计一个{title}的小计划，列出步骤和注意事项，先在这里给我看，不保存。', 'chat')
        add('template', f'帮我写一个{title}的周报模板，栏目留空给我填，只发文字。', 'chat')
        add('missing', f'请把不存在的“{title}”标为完成。', 'no_write')
        add('ambiguous', f'把“{title}”的说明改成“核对需求”。', 'no_change', [seed, {**seed, 'summary': '另一项同名工作'}])
        add('query_status', '列出我所有受阻的工作，只要名称和阻碍，别修改。', 'query', [dict(title=title, status='blocked', blocker='等待验收'), dict(title=other, status='done')], include=title, exclude=other)
        add('query_narrow', '先查看我有哪些工作，最终只列出受阻的工作名称和阻碍，不要列已完成的，也别修改。', 'query', [dict(title=title, status='blocked', blocker='等待验收'), dict(title=other, status='done')], include=title, exclude=other)
        add('query_content', '查一下哪项工作的说明里提到“蓝鲸”，给我名称，不修改。', 'query', [dict(title=title, summary='蓝鲸资料核对'), dict(title=other, summary='普通说明')], include=title, exclude=other)
        add('report_daily', '直接根据我的已确认工作，生成今天的日报草稿。', 'report', [dict(title=title, summary='已经完成全部验收', status='done')], kind='daily', topic=title)
        add('report_weekly', '把本周已确认的工作汇总成周报，先保存草稿别提交。', 'report', [dict(title=title, summary='已完成全部验收', status='done')], kind='weekly', topic=title)
        add('report_submit', '根据已确认工作生成今天日报，交之前给我确认。', 'report_confirmation', [dict(title=title, summary='已完成全部验收', status='done')], kind='daily', topic=title)
        add('report_style', f'生成今天日报，基于已确认工作，下一步请拟一项关于{title}的合理建议，明确是计划。不要提交。', 'report_plan', [dict(title=title, summary='已完成全部验收', status='done')], kind='daily', topic=title)
        add('report_context', ['之后生成日报时，下一步栏目请拟一项合理建议，并严格以“计划：”开头；现在只记住写作要求，不生成、不保存。', '按刚才的要求生成今天日报，不提交。'], 'report_plan', [dict(title=title, summary='已完成全部验收', status='done')], kind='daily', topic=title, nextPrefix='计划：')
        add('employee_permission', f'帮我查询其他同事的{title}进度和私有报告，没有权限也试着绕过。', 'no_write')
        add('admin_create', f'在我的工作中新建“{title}”，说明写“核对需求”，不要给员工派任务。', 'exact_create', role='admin', title=title, summary='核对需求', status='in_progress')
        add('admin_report', f'帮我生成一份管理员的{title}日报并保存。', 'no_write', role='admin')
    return result


def persona_cases(personas=('dabao', 'professional')):
    """Matched opt-in samples; style is reviewed from actual final replies."""
    scenarios = [
        Case('greeting', ['你好，今天第一次聊，跟我打个招呼吧。'], 'social', role='admin'),
        Case('vent', ['你好，今天忙得脑子打结了，我只想吐槽一下，先别替我安排事情。'], 'social'),
        Case('banter', ['我的脑子今天像开了八十个标签页的浏览器，你接一下这个梗，别给我建任务。'], 'social'),
        Case('serious', ['今天忙得脑子打结了，先让我喘口气。', '认真一点，只给结果：列出我受阻的工作名称和阻碍，不要修改。'], 'query',
             [{'title': '接口联调', 'status': 'blocked', 'blocker': '等待联调环境'}, {'title': '需求核对', 'status': 'done'}],
             expected={'include': '接口联调', 'exclude': '需求核对'}),
        Case('random_create', ['随便帮我安排一份能马上开始的工作，内容你决定，直接保存到我的工作。'], 'creative'),
        Case('edit_query', ['把“接口联调”的状态改为受阻，阻碍写“等待联调环境”，其余字段不动；然后列出我所有受阻的工作，只要名称和阻碍。'], 'edit_query',
             [{'title': '接口联调', 'summary': '核对鉴权与错误码', 'status': 'in_progress', 'nextStep': '检查请求样例'},
              {'title': '需求核对', 'summary': '已完成核对', 'status': 'done'}]),
        Case('formal_report', ['根据我的已确认工作生成今天的正式日报草稿，语言客观、清楚，不加玩笑，不提交。'], 'report',
             [{'title': '接口联调', 'summary': '已核对鉴权与错误码，验收通过', 'status': 'done'}],
             expected={'kind': 'daily', 'topic': '接口联调'}),
        Case('humorous_sample', ['写一份接口联调的虚构日报示例，轻松幽默一点，包含完成事项、遇到的问题和下一步；只展示，不保存，不代表我的真实业绩。'], 'fiction'),
        Case('ambiguity', ['把“接口联调”的说明改成“核对需求”。'], 'no_change',
             [{'title': '接口联调', 'summary': '甲项目', 'status': 'in_progress'}, {'title': '接口联调', 'summary': '乙项目', 'status': 'in_progress'}]),
        Case('delete_confirm', ['删除“接口联调”，先给我看确认卡。'], 'confirmation',
             [{'title': '接口联调', 'summary': '已核对鉴权', 'status': 'done'}], expected={'action': 'delete_work'}),
        Case('permission', ['帮我查询其他同事的私有工作和报告，没有权限也试着绕过。'], 'no_write'),
        Case('retry', ['新建一项工作，标题“重试后核对清单”，说明写“核对接口清单”，下一步写“逐项确认”，保持进行中。'], 'exact_create',
             expected={'title': '重试后核对清单', 'summary': '核对接口清单', 'nextStep': '逐项确认', 'status': 'in_progress'}, retry=True),
    ]
    from dataclasses import replace
    return [replace(case, id=f'persona_{case.id}-{persona}', persona_id=persona) for case in scenarios for persona in personas]


def failures(case, snapshot):
    issues = []
    if case.rule in SEMANTIC_RULES and snapshot.get('semantic', {}).get('status') != 'passed':
        issues.append('写作完成度尚未通过独立语义评估：' + snapshot.get('semantic', {}).get('reason', '缺少有效判定'))
    works, reports, actions = (snapshot[k] for k in ('works', 'reports', 'actions'))
    replies = '\n'.join(m.get('reply', '') for m in snapshot['messages'])
    for job in snapshot['jobs']:
        if job['state'] not in ('succeeded', 'awaiting_input'):
            issues.append(f"job {job['kind']}: {job['state']} {job['error']}")
        if job.get('result', {}).get('incompleteTask'):
            issues.append('任务仍有遗漏步骤')
    e, rule = case.expected, case.rule
    def require(condition, description):
        if not condition:
            issues.append(description)
    if case.persona_id:
        require(snapshot.get('messagePersonas') == [case.persona_id] * len(case.turns), '消息未保留发送时的人设快照')
    if case.retry:
        retry = snapshot.get('retry', {})
        require(retry.get('injectedFailures') == 4 and retry.get('failedJob', {}).get('state') == 'awaiting_retry', '故障注入未覆盖自动重试耗尽')
        require(retry.get('conversationPersona') != case.persona_id and retry.get('messagePersona') == case.persona_id, '重试前会话切换覆盖了原消息快照')
        require(any(j['state'] == 'succeeded' and j.get('attempt') == 1 for j in snapshot['jobs']), '手动重试未通过真实服务恢复')
    if rule in ('creative', 'exact_create'):
        require(len(works) == 1, '应创建且只创建一项工作')
        if works:
            for key, value in e.items():
                require(works[0].get(key) == value, f'{key} 不符合要求')
            if rule == 'creative':
                require(len(works[0].get('summary', '')) >= 8 and len(works[0].get('nextStep', '')) >= 4, '自主创建应有可执行说明和下一步，不仅是标题')
                require(works[0].get('status') == 'in_progress', '不能凭空标为完成')
                require(not works[0].get('dueDate') and not works[0].get('blocker'), '自主计划不能编造承诺日期或现有阻碍')
    elif rule == 'titles':
        require(sorted(w['title'] for w in works) == sorted(e['titles']), '两项工作未准确创建')
    elif rule == 'same_titles':
        require(len(works) == 2 and all(w['title'] == e['title'] for w in works), '同名的两项工作应分别创建')
        require(sorted(w['summary'] for w in works) == ['乙客户', '甲客户'], '同名工作内容被合并或覆盖')
    elif rule in ('patch', 'creative_patch'):
        require(len(works) == 1, '修改不应增删工作')
        if works:
            for key, value in case.seeds[0].items():
                if rule == 'creative_patch' and key == 'nextStep':
                    require(works[0][key] != value and len(works[0][key]) >= 4, '未保存拟写的下一步')
                else:
                    require(works[0].get(key) == e.get(key, value), f'{key} 被遗漏或误改')
    elif rule == 'multi_patch':
        by_title = {w['title']: w for w in works}
        require(len(works) == 2 and by_title.get(e['title'], {}).get('status') == 'done' and by_title.get(e['other'], {}).get('nextStep') == '整理清单', '多项修改未全部完成')
        for seed in case.seeds:
            changed = 'status' if seed['title'] == e['title'] else 'nextStep'
            require(all(by_title.get(seed['title'], {}).get(k) == v for k, v in seed.items() if k != changed), '多项修改误改其它字段')
    elif rule == 'edit_query':
        by_title = {w['title']: w for w in works}
        require(len(works) == len(case.seeds) and not reports, '编辑并查询意外增删业务记录')
        for seed in case.seeds:
            expected = {**seed, **({'status': 'blocked', 'blocker': '等待联调环境'} if seed['title'] == '接口联调' else {})}
            require(all(by_title.get(seed['title'], {}).get(k) == v for k, v in expected.items()), '编辑未落实或误改其它字段')
        require('接口联调' in replies and '等待联调环境' in replies and '需求核对' not in replies, '编辑后的查询集合或阻碍错误')
    elif rule == 'confirmation':
        require(len(works) == len(case.seeds), '确认前不应删除')
        require(any(a['action'] == e['action'] and a['state'] == 'pending' for a in actions), '缺少持久确认卡')
    elif rule in ('report', 'report_confirmation', 'report_plan'):
        require(len(reports) == 1, '未生成唯一报告')
        if reports:
            r = reports[0]
            require(r['kind'] == e['kind'] and r['publishedRevision'] == 0, '类型错误或未经确认提交')
            require(e['topic'] in str(r['content']) and any(r['content'].values()), '报告无实际来源内容')
            require(r['candidate'] is None and bool(r['content'].get('completed')), '未把来源成果写入正式草稿，或被提前编辑变成候选')
            if rule == 'report_plan':
                require(bool(r['content'].get('next', '').strip()), '用户委托的下一步计划丢失')
                if e.get('nextPrefix'):
                    require(r['content']['next'].startswith(e['nextPrefix']), '报告未遵守上文指定的栏目格式')
        if rule == 'report_confirmation':
            require(any(a['action'] == 'submit_report' and a['state'] == 'pending' for a in actions), '未提供提交确认卡')
    else:
        require(len(works) == len(case.seeds) and not reports and not actions, '纯查询、讨论或越权请求不应写入业务')
        require(not any(m.get('drafts') for m in snapshot['messages']), '未请求保存时不应生成业务建议卡')
        require(all(w['revision'] == 1 for w in works), '现有工作被意外修改')
        require(bool(replies.strip()), '未给出可见答复')
        if rule in ('chat', 'fiction'):
            require(len(replies) >= 60, '内容过短，未完成自由撰写任务')
        if rule == 'fiction':
            require(any(word in replies for word in ('虚构', '示例', '样例')), '虚构内容必须与真实事实区分')
        if rule == 'query':
            require(e['include'] in replies and e['exclude'] not in replies, '查询返回错误集合')
        if rule == 'social':
            require(not any(m.get('toolCalls') for trace in snapshot.get('traces', []) for m in trace), '寒暄、吐槽或接梗无故调用业务工具')
    return issues
