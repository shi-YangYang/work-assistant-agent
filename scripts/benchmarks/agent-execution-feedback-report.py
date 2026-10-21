"""Render preserved real Spec075 runs; never fabricate or discard failed replies."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, nargs='+', required=True)
    parser.add_argument('--after', type=Path, nargs='+', required=True)
    parser.add_argument('--invalid', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args()


def load(paths):
    rows = []
    for path in paths:
        source = path / 'results.jsonl' if path.is_dir() else path
        if source.exists():
            environments = list(source.parent.glob('environment-*.json'))
            metadata = [json.loads(item.read_text()) for item in environments]
            for number, line in enumerate(source.read_text().splitlines(), 1):
                row = json.loads(line)
                row['_source'] = str(source.resolve()) + ':' + str(number)
                row['_sourceVersions'] = sorted({item['digest'] for item in metadata})
                row['_sourceRoots'] = sorted({item['source'] for item in metadata})
                rows.append(row)
    return rows


def number(value):
    return '未测得' if value is None else f'{value / 1000:.2f} 秒'


def first(row):
    return row.get('first_effective_ms', row.get('first_answer_ms'))


def public_observation(row):
    original_origin = row.get('first_effective_origin')
    first_text = next((item for item in row.get('stream', []) if item.get('text')), None)
    text_origin = None
    correction = None
    # An early model preamble can be replaced by a later program question.
    # Attribute the observed fragment itself, never the final answer's origin.
    if row.get('publicObservationVersion', 0) >= 2 and first_text:
        ends = [event for event in row.get('events', []) if event.get('event') == 'model.end']
        for index, request in enumerate(row.get('requests', [])):
            kind = request.get('kind') or (ends[index].get('kind') if index < len(ends) else None)
            if kind == 'main' and any(item['text'].startswith(first_text['text']) for item in request.get('publicContent', [])):
                text_origin = 'model:stream_prefix_of_public_content'
                break
        if not text_origin:
            text_origin = 'unclassified:public_stream_fragment'
    effective_origin = original_origin
    if first_text and row.get('first_effective_source') == 'public Redis event' and text_origin:
        effective_origin = text_origin
        if original_origin != effective_origin:
            correction = '原始 first_effective_origin 套用了最终回复来源；本字段按实际首流片段重判，原始记录未修改。首片段不等于已完成回复或可操作问题。'
    question_times = [event['at_ms'] for event in row.get('questionEvents', []) if event.get('origin', '').startswith('program:')]
    return {
        'version': row.get('publicObservationVersion'),
        'answerOrigin': row.get('answer_origin', '未记录；不从旧回复反推来源'),
        'firstEffectiveSource': row.get('first_effective_source'),
        'firstEffectiveOrigin': effective_origin,
        'recordedFirstEffectiveOrigin': original_origin,
        'originCorrection': correction,
        'firstPublicText': ({'atMs': first_text['at_ms'], 'text': first_text['text'], 'origin': text_origin}
                            if first_text else None),
        'firstProgramQuestionMs': min(question_times) if question_times else None,
        'questionEvents': row.get('questionEvents'),
        'deliveryEvents': row.get('deliveryEvents'),
        'modelPublicContent': [{'request': index + 1, 'content': request['publicContent']}
            for index, request in enumerate(row.get('requests', [])) if request.get('publicContent')],
        'modelPublicContentRecorded': row.get('publicObservationVersion', 0) >= 2,
    }


def outcome(row):
    return row.get('message', {}).get('job', {}).get('taskOutcome', {}).get('state', '未完成')


def effects(row):
    initial, final = row.get('initial', {}), row.get('final', {})
    old = {work['id']: work for work in initial.get('works', [])}
    new = [work for work in final.get('works', []) if work['id'] not in old]
    changed = [work for work in final.get('works', []) if work['id'] in old and work != old[work['id']]]
    before_materials = {item['id'] for item in initial.get('materials', [])}
    materials = [item for item in final.get('materials', []) if item['id'] not in before_materials and not item['removed']]
    removed = [item for item in final.get('materials', []) if item['id'] in before_materials and item['removed']]
    source_order = {item['deliverableId']: index + 1 for index, item in enumerate(row.get('seed', {}).get('artifacts', []))}
    reports = len(final.get('reports', [])) - len(initial.get('reports', []))
    return {'newWorks': len(new), 'newWorkTitles': [item['content'].get('title') for item in new], 'changedWorks': len(changed), 'newMaterials': len(materials), 'removedMaterials': len(removed), 'newReports': reports, 'materialSources': [item['source'] for item in materials], 'materialWorkIds': sorted({item['workId'] for item in materials}), 'materialGenerationIndices': [source_order.get(item['source'].get('deliverableId')) for item in materials], 'changedContent': [item['content'] for item in changed], 'changedFields': [sorted(key for key in set(item['content']) | set(old[item['id']]['content']) if item['content'].get(key) != old[item['id']]['content'].get(key)) for item in changed]}


def stages(row):
    result = defaultdict(lambda: {'calls': 0, 'ms': 0})
    requests = row.get('requests', [])
    ends = [event for event in row.get('events', []) if event.get('event') == 'model.end']
    for index, request in enumerate(requests):
        kind = request.get('kind') or (ends[index].get('kind') if index < len(ends) else 'unknown')
        result[kind]['calls'] += 1
        result[kind]['ms'] += request.get('elapsed_ms', 0)
    return dict(result)


def inputs(row):
    requests = row.get('requests', [])
    tokens = [item['usage']['prompt_tokens'] for item in requests if isinstance(item.get('usage', {}).get('prompt_tokens'), (int, float))]
    seed = row.get('seed', {})
    return {
        'historyCount': seed.get('historyCount'),
        'historyChars': seed.get('historyChars'),
        'fixtureSha256': seed.get('fixtureSha256'),
        'fixtureDifferences': seed.get('differences', []),
        'firstRequestInputTokens': requests[0].get('usage', {}).get('prompt_tokens') if requests else None,
        'requestInputTokensRange': [min(tokens), max(tokens)] if tokens else None,
        'wireReasoningEfforts': sorted({item.get('parameters', {}).get('reasoning_effort') for item in requests if item.get('parameters', {}).get('reasoning_effort')}),
    }


def checks(row):
    issues = []
    if row.get('error'):
        issues.append('运行异常：' + row['error']['type'])
    if row.get('preparedOnly'):
        issues.append('仅准备fixture，不是真实模型结果')
    if not row.get('requests'):
        issues.append('没有真实模型调用')
    effect = effects(row)
    case = row['case']
    if case == 'E01' and effect['newMaterials'] != 11:
        issues.append('未完整新增11份材料')
    if case in ('E03', 'E04', 'E07', 'E08', 'E09', 'E17') and effect['newMaterials'] != 2:
        issues.append('未完整新增2份材料')
    if case in ('E00-A', 'E00-B', 'E01', 'E03', 'E04', 'E07', 'E08', 'E09', 'E10', 'E16', 'E17'):
        def identity(source):
            return source.get('deliverableId'), source.get('revision'), source.get('fileId')
        expected_sources = {identity(item) for item in row.get('seed', {}).get('artifacts', [])}
        saved_sources = {identity(item) for item in effect['materialSources']}
        if saved_sources and saved_sources != expected_sources:
            issues.append(f'已知全部集合未准确保存：期望{len(expected_sources)}份，实际{len(saved_sources)}份')
        if outcome(row) == 'completed' and saved_sources != expected_sources:
            issues.append('全部材料未保存却标为completed')
    if case in ('E04', 'E09', 'E10', 'E16', 'E17') and effect['newWorks'] != 1:
        issues.append('没有按明确请求新建恰好一条工作')
    if case in ('E01', 'E03', 'E07', 'E08'):
        if any(value != row.get('seed', {}).get('workId') for value in effect['materialWorkIds']) or effect['newWorks']:
            issues.append('材料未绑定到明确引用的原工作')
    if effect['removedMaterials']:
        issues.append('已有材料被移除，需核对请求范围')
    if case in ('E01', 'E03', 'E07', 'E08') and any(set(fields) - {'materialIds'} for fields in effect['changedFields']):
        issues.append('材料以外的工作字段发生变化，需核对请求范围')
    if case == 'E05':
        issues.append('原始fixture未给用户统一编号；按生成顺序期望2/4，目录实际倒序，澄清或倒序选择需人工解释')
    if case in ('E06', 'E12', 'E13', 'E14-Q', 'E14-R', 'E15', 'E18') and any(effect[key] for key in ('newWorks', 'changedWorks', 'newMaterials', 'newReports')):
        issues.append('出现非预期业务写入')
    if case == 'E14-R':
        reply = row.get('answer', '').replace(',', '').replace('，', '')
        if '12800' not in reply or not ('2026-11-06' in reply or '2026 年 11 月 6 日' in reply or '2026年11月6日' in reply):
            issues.append('固定预算/日期需人工复核')
    if case == 'E14-W':
        if effect['changedWorks'] != 1 or any(item.get('status') != 'done' for item in effect['changedContent']):
            issues.append('没有准确完成一条已有工作')
        if any(set(fields) - {'status'} for fields in effect['changedFields']):
            issues.append('修改状态时同时改变了其他工作字段')
    if case == 'E11' and outcome(row) == 'completed':
        issues.append('要求先问新工作名称的待完成分支被标为completed')
    if case == 'E12':
        if 'peerWorkInitial' not in row or 'peerWorkFinal' not in row:
            issues.append('早期样本缺同事对象前后快照，不能据本人无写入判断同事对象未变')
        elif row['peerWorkInitial'] != row['peerWorkFinal']:
            issues.append('同事对象前后不一致，需检查是否发生越权变更')
    if case != 'E18':
        reply = row.get('answer', '')
        flags = [token for token in ('服务端', '变更计划', 'materials', 'requiredFields', '没放行', '系统拦', '系统这次又拦', '系统第二次拦') if token in reply]
        if flags:
            issues.append('公开回复含内部说明候选：' + '、'.join(flags))
    if not row.get('refreshSameReply', False):
        issues.append('未验证刷新正文一致')
    return issues


def main(options):
    rows = load(options.before) + load(options.after)
    invalid = load(options.invalid)
    grouped = defaultdict(list)
    duplicates = defaultdict(list)
    for row in rows:
        grouped[(row['case'], row['effort'], row['label'])].append(row)
        duplicates[(row['case'], row['effort'], row['label'], row['sample'])].append(row)
    repeated = {key: value for key, value in duplicates.items() if len(value) > 1}
    if repeated:
        raise ValueError('同一采样槽含多份记录；候选失败必须单独报告，不能混入最终版统计：' + str(list(repeated)))
    manifest = json.loads(Path(__file__).with_name('agent-execution-feedback-cases.json').read_text())
    missing = [{'case': item['id'], 'effort': effort, 'label': label, 'sample': sample} for item in manifest['cases'] for effort in manifest['efforts'] for label in ('before', 'after') for sample in range(item['samples']) if (item['id'], effort, label, sample) not in duplicates]
    sections = ['# Spec075 真实模型前后对照', '',
                '所有运行均调用真实模型并经过真实 API/worker 链路，用户可见回复也可能由程序生成问题或业务回执。新版观察器单独记录这类来源和模型公开文本；未记录来源的旧样本不反向推断。历史业务数据经过脱敏，原始文件替换为有效隔离素材。本文中的检查是固定事实核对与人工复核线索，不是模型裁判，也不替代验收。', '',
                '计时从本地 ASGI 消息提交开始，到持久化结果可读结束，不含真实浏览器绘制、网络传输和周期性 worker 轮询。首有效内容优先取公开 Redis 正文或问题事务提交后可查询时间；早期基线未安装问题时刻观测，只记录正文时刻。首个公开字符不等于整段回答完成。模型阶段是调用耗时累加，工具并行时不可直接当作墙钟占比。', '',
                '早期 E00 与普通 baseline 样本存在最多两个评测进程并行；样本0、提前完成的E14-Q基线和返工等待期间补齐的基线并非全部严格交替。本地定向测试可能同时运行，未隔离主机CPU/IO，也未控制服务商负载，计时存在时段/并发混杂，不能把全部耗时差归因代码。失败样本保留，不重跑到绿。', '',
                '## 版本与计划覆盖', '',
                *[f"- {label} 源码：{', '.join(sorted({digest for row in rows if row['label'] == label for digest in row['_sourceVersions']})) or '未记录'}。" for label in ('before', 'after')],
                f"- 预注册采样槽共 {sum(item['samples'] for item in manifest['cases']) * 4} 个，实际记录 {len(rows)} 个，尚未执行 {len(missing)} 个。", '',
                '## 样本汇总', '', '| 用例 | 档位 | 版本 | 样本 | 任务结果 | 首有效内容 | 总耗时 | 模型调用 | 写入结果（新增工作/修改工作/材料/报告） |', '|---|---|---|---:|---|---:|---:|---:|---|']
    for row in sorted(rows, key=lambda r: (r['case'], r['effort'], r['sample'], r['label'])):
        effect = effects(row)
        sections.append(f"| {row['case']} | {row['effort']} | {row['label']} | {row['sample']} | {outcome(row)} | {number(first(row))} | {number(row.get('total_ms'))} | {len(row.get('requests', []))} | {effect['newWorks']}/{effect['changedWorks']}/{effect['newMaterials']}/{effect['newReports']} |")
    sections += ['', '## 核心三组分布', '', '| 用例 | 档位 | 版本 | 样本数 | 首有效中位数（范围） | 总耗时中位数（范围） | 模型调用中位数（范围） |', '|---|---|---|---:|---|---|---|']
    distributions = []
    for case in ('E00-A', 'E00-B', 'E07', 'E14-Q', 'E14-R', 'E14-W'):
        for effort in ('low', 'high'):
            for label in ('before', 'after'):
                samples = grouped[(case, effort, label)]
                record = {'case': case, 'effort': effort, 'label': label, 'n': len(samples)}
                text = []
                for field, getter, formatter in (('first', first, number), ('total', lambda row: row.get('total_ms'), number), ('calls', lambda row: len(row.get('requests', [])), str)):
                    values = [getter(row) for row in samples if getter(row) is not None]
                    record[field] = {'median': statistics.median(values), 'min': min(values), 'max': max(values)} if values else None
                    text.append(f"{formatter(statistics.median(values))}（{formatter(min(values))}–{formatter(max(values))}）" if values else '未测得')
                sections.append(f"| {case} | {effort} | {label} | {len(samples)} | {' | '.join(text)} |")
                distributions.append(record)
    sections += ['', '## 正常路径性能门槛', '']
    performance = []
    for case in ('E14-Q', 'E14-R', 'E14-W'):
        for effort in ('low', 'high'):
            before, after = grouped[(case, effort, 'before')], grouped[(case, effort, 'after')]
            record = {'case': case, 'effort': effort, 'beforeN': len(before), 'afterN': len(after), 'metrics': {}}
            if len(before) < 3 or len(after) < 3:
                sections.append(f'- {case} {effort}：不足完整三组，当前 before={len(before)}、after={len(after)}，未判通过。')
            for field, getter in (('total_ms', lambda row: row.get('total_ms')), ('first_effective_ms', first)):
                left, right = [getter(r) for r in before if getter(r) is not None], [getter(r) for r in after if getter(r) is not None]
                if not left or not right:
                    continue
                base, changed = statistics.median(left), statistics.median(right)
                threshold = base + max(base * .1, 2000)
                passed = changed <= threshold
                record['metrics'][field] = {'beforeMedian': base, 'afterMedian': changed, 'beforeRange': [min(left), max(left)], 'afterRange': [min(right), max(right)], 'limit': threshold, 'withinThreshold': passed}
                sections.append(f"- {case} {effort} {field}：{number(base)} → {number(changed)}；上限 {number(threshold)}；{'在门槛内' if passed else '回退，必须调查'}。")
            if before and after:
                old = statistics.median(len(r.get('requests', [])) for r in before)
                new = statistics.median(len(r.get('requests', [])) for r in after)
                record['callsMedian'] = {'before': old, 'after': new, 'notIncreased': new <= old}
                if new > old:
                    sections.append(f'- {case} {effort} 模型调用中位数增加 {old} → {new}，必须调查。')
            performance.append(record)
    sections += ['', '## 真实用户可见回复与副作用', '']
    for row in sorted(rows, key=lambda r: (r['case'], r['effort'], r['sample'], r['label'])):
        sections += [f"### {row['case']} / {row['effort']} / 样本 {row['sample']} / {row['label']}", '', '**用户输入**：' + row['prompt'], '', '**真实用户可见回复**：', '', row.get('answer') or '（没有可交付正文；查看下方错误与任务状态，不补写答案。）', '', '**回复来源**：' + public_observation(row)['answerOrigin'], '', '**结果**：' + outcome(row), '', '```json', json.dumps({'effects': effects(row), 'modelStages': stages(row), 'firstEffectiveMs': first(row), 'publicObservation': public_observation(row), 'totalMs': row.get('total_ms'), 'inputs': inputs(row), 'checksNeedingReview': checks(row), 'error': row.get('error'), 'outcome': row.get('message', {}).get('job', {}).get('taskOutcome'), 'interactions': row.get('interactions'), 'peerWorkInitial': row.get('peerWorkInitial'), 'peerWorkFinal': row.get('peerWorkFinal'), 'sourceVersions': row['_sourceVersions']}, ensure_ascii=False, indent=2), '```', '', '原始证据：`' + row['_source'] + '`', '']
    sections += ['## 覆盖限制', '', '- live 权限均为 full；ask/auto、故障注入、重启/断线恢复、拆分流式内部字段等以对应确定性业务链与 Web 验证另行说明。', '- E07/E08 未自然触发目标故障时，只能证明正常路径，没有以假模型强制造出失败。E15为有效上传后受控文件损坏，后续回复使用真实模型。', '- E00 两组同主题文件均为独立成果、各revision1；保留11个ID与历史顺序，没有按名字合并。', '- E05未预先给统一显示编号，生成顺序与目录倒序不同；不能将澄清顺序直接算作多余确认。', '- E06正文文件访问与成果记录说明是两回事；无法访问正文的实际结果保留，不能当作完整读过文件。', '- 只有小样本，列中位数、范围与最慢样本；没有宣称可靠P95。', '', '## 评测装配错误/早期诊断记录', '']
    for row in invalid:
        sections.append(f"- {row['case']} {row['effort']} {row['label']} {row['sample']}：{row.get('error') or row.get('message', {}).get('job', {}).get('error') or '早期装配版本；完整记录保留'}；真实模型调用 {len(row.get('requests', []))} 次；{row['_source']}")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text('\n'.join(sections) + '\n')
    options.output.with_suffix('.json').write_text(json.dumps({'performance': performance, 'coreDistributions': distributions, 'missing': missing, 'rows': [{'case': row['case'], 'effort': row['effort'], 'label': row['label'], 'sample': row['sample'], 'effects': effects(row), 'stages': stages(row), 'publicObservation': public_observation(row), 'checks': checks(row), 'source': row['_source'], 'sourceVersions': row['_sourceVersions']} for row in rows], 'invalidCount': len(invalid)}, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main(args())
