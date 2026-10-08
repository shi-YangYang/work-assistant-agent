"""Optional, source-bound length checks; no model call and no inferred intent."""
import math
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.agent.completion.limits import MAX_ANSWER_LENGTH


class AnswerLength(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote: str = Field(min_length=1, max_length=160)
    unit: Literal['cjk_characters', 'words']
    body: str = Field(min_length=1, max_length=MAX_ANSWER_LENGTH)


NUMBER = r'([1-9]\d{0,5})'
UNIT = r'(字|(?:English\s*)?words?|(?:个\s*)?(?:英文\s*)?(?:单词|词))'
RANGE = re.compile(rf'(?:英文\s*)?{NUMBER}\s*(?:到|至|[-–]|to)\s*{NUMBER}\s*{UNIT}', re.I)
SINGLE = re.compile(rf'(约|大约|至少|不少于|最多|不超过|精确|恰好|正好|about|around|at least|at most|under|exactly)?\s*(?:英文\s*)?{NUMBER}\s*{UNIT}\s*(左右|以内|以下|以上)?', re.I)
WORDS = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
PREFIX = re.compile(r'(?:(?:约|大约|至少|不少于|最多|不超过|精确|恰好|正好|about|around|at least|at most|under|exactly)\s*(?:英文\s*)?|英文\s*)$', re.I)
SUFFIX = re.compile(r'^\s*(?:左右|以内|以下|以上)')
TITLE = re.compile(r'^\s*(?:#{1,6}\s+[^\n]{1,120}|《[^》\n]{1,120}》)\s*\n+\s*$')


def bounds(requirement, request):
    quote = requirement.quote.strip()
    # Reject a truncated numeric suffix, e.g. 200 words taken from 1200 words.
    if not any(not (quote[0].isdigit() and match.start() and request[match.start() - 1].isdigit())
               and not PREFIX.search(request[:match.start()]) and not SUFFIX.match(request[match.end():])
               for match in re.finditer(re.escape(quote), request)):
        raise ValueError('长度要求必须逐字引用当前请求中的完整数值与单位。')
    match = RANGE.fullmatch(quote)
    if match:
        lower, upper, unit = int(match[1]), int(match[2]), match[3]
        if lower > upper:
            raise ValueError('长度范围顺序无效。')
    else:
        match = SINGLE.fullmatch(quote)
        if not match:
            raise ValueError('长度要求仅支持阿拉伯数字的字数或 word 数，不能自行编造范围。')
        prefix, count, unit, suffix = (match[1] or '').lower(), int(match[2]), match[3], match[4] or ''
        if prefix and suffix:
            raise ValueError('长度限定只能声明一个明确的范围。')
        if prefix in ('约', '大约', 'about', 'around') or suffix == '左右':
            lower, upper = math.ceil(count * .8), math.floor(count * 1.2)
        elif prefix in ('至少', '不少于', 'at least') or suffix == '以上':
            lower, upper = count, None
        elif prefix in ('最多', '不超过', 'at most') or suffix in ('以内', '以下'):
            lower, upper = 0, count
        elif prefix == 'under':
            lower, upper = 0, count - 1
        elif prefix in ('精确', '恰好', '正好', 'exactly'):
            lower = upper = count
        else:
            # An unqualified writing length is a target, not an exact-match task.
            lower, upper = math.ceil(count * .8), math.floor(count * 1.2)
    expected = 'cjk_characters' if unit == '字' else 'words'
    if unit == '字' and '英文' in quote:
        raise ValueError('英文字符数不等于单词数，此处只支持英文单词计数。')
    if requirement.unit != expected:
        raise ValueError('计数单位与用户原文不一致。')
    return lower, upper


def validate_reference(requirement, answer, request):
    limits = bounds(requirement, request)
    if requirement.body not in answer or answer.count(requirement.body) != 1:
        raise ValueError('计数正文必须是 answer 中唯一、连续的实际正文，不能另造内容。')
    prefix, suffix = answer.split(requirement.body)
    if suffix.strip() or prefix.strip() and not TITLE.fullmatch(prefix):
        raise ValueError('计数必须包含完整正文；只可排除开头的单行 Markdown 标题或《标题》，不能挑选局部内容。')
    return limits


def check_length(requirement, answer, request):
    if requirement is None:
        return ''
    try:
        lower, upper = validate_reference(requirement, answer, request)
    except ValueError as error:
        return '长度约束无法核对：' + str(error)
    count = (len(re.findall(r'[\u3400-\u9fff\U00020000-\U000323af]', requirement.body))
             if requirement.unit == 'cjk_characters' else len(WORDS.findall(requirement.body)))
    if count >= lower and (upper is None or count <= upper):
        return ''
    target = f'{lower}–{upper}' if upper is not None else f'至少 {lower}'
    label = '汉字（不含标点）' if requirement.unit == 'cjk_characters' else 'words'
    return f'用户要求“{requirement.quote}”；实际正文为 {count} {label}，要求 {target}。请完整改写正文满足该范围，不添加虚构字数声明。保留正文之外的标题和说明原文，以便核对同一正文。'


def rebind_body(requirement, previous, answer):
    """Keep the declared body boundary during the existing one-shot text repair."""
    old = requirement['body']
    if not old or previous.count(old) != 1:
        return requirement
    prefix, suffix = previous.split(old)
    if answer.startswith(prefix) and answer.endswith(suffix):
        body = answer[len(prefix):len(answer) - len(suffix) if suffix else None]
        if body:
            return {**requirement, 'body': body}
    # An unlocatable body stays invalid; never silently remove its constraint.
    return requirement


LENGTH_POLICY = '''本轮用户明确要求正文长度，且是阿拉伯数字的汉字数或英文 word 数时，finish_task 的 answer_length 填 quote（逐字引用完整长度短语）、unit（cjk_characters 或 words）、body（answer 中的连续完整正文，可仅排除开头单行 Markdown 标题或《标题》，不另附说明）。服务端本地计数；裸数字和约数按目标的 80%–120%，仅精确/恰好/正好/exactly 要求精确计数，范围/至少/最多/以内按原文。不能自行缩小正文片段凑数，也不能把示例、引用材料或旧消息里的数值当本轮要求。没有适用的明确长度要求时省略该字段，不为其它格式猜长度。不要附带未经计数的“约多少字”声明；只交付用户要求的内容。\n'''
