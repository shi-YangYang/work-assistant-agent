"""Route numeric explanations to consistency review, without judging their truth."""
import re

NON_QUANTITIES = re.compile(
    r'```[\s\S]*?```|`[^`\n]*`|https?://[^\s<>\]\)]+|'
    r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\d{4}年\d{1,2}月\d{1,2}日|'
    r'\b\d{1,2}:\d{2}(?::\d{2})?\b|\b[vV]?\d+(?:\.\d+){2,}\b',
)
ORDINAL = re.compile(r'^\s*\d+[.)、．]\s*', re.MULTILINE)
NUMBER = re.compile(r'(?<![A-Za-z0-9_])[-−+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[%％])?(?![A-Za-z0-9_])')
RELATION = re.compile(
    r'[=＝+＋×÷]|(?<=\d)\s*[-−*/]\s*(?=\d)|'
    r'合计|总计|总共|共有|就是|得到|总额|净额|差额|相差|剩余|其中|里有|组成|构成|占比|比例|比率|等于|高于|低于|增加|减少|'
    r'\b(?:total|net|sum|difference|remaining|equals?|ratio|percent|comprises?|consists?|includes?)\b',
    re.IGNORECASE,
)


def quantitative_scope(answer):
    prose = ORDINAL.sub('', NON_QUANTITIES.sub('', answer))
    quantities = NUMBER.findall(prose)
    if len(quantities) < 3 or len(set(quantities)) < 2 or not RELATION.search(prose):
        return None
    # This is a review trigger, never a statement that an answer is incorrect.
    return {'kind': 'quantitative_consistency', 'numericTerms': quantities[:64]}


QUANTITATIVE_POLICY = '''quantitativeConsistency 存在时，只增加答复内部量化一致性检查：从当前问题、对话中明确的已知条件与答复自己的假设出发，核对等式、总额/净额/余额、组成/占比、单位与期间是否一致。计算数值正确但解释把一个余额放进不相容的净额或把部分和整体混为一谈，也属于具体矛盾。把候选文本中的关系写成关系式再比对，不能仅因前一句计算正确就放过后面的解释。
未给出的条件可以作为明确假设，假设例子不需要外部证据，不能要求联网或沙盒。后续改写不能悄悄把助手假设变成用户已提供的事实，也不能删掉决定结果的前提。只检查已有数值及假设，不能引入额外事实或把“现实还可能有其他因素”当作错误。不要改变授权、可选建议、人设、比喻或风格；正常比喻只有明确把数值关系解释错时才指出。
存在可证实的内部矛盾时用 kind=fact，quote 精确引用发生矛盾的候选原文，reason 说明相关量分别是什么、何处矛盾以及应保留的前提，evidence/receipt_ids 没有对应工具事实时为空；不要求凭空编证据 ID。没有具体矛盾 issues=[]，正确答案完整原样保留。reviewScope=quantitative_only 时只允许这种 fact，不核对其它业务、权限或普通事实，也不凭缺少外部资料要求补充信息。'''
