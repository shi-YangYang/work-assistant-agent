import json
import re
from fastapi import HTTPException
from paa_server.security.ownership import owned


def clip(value):
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered[:6000]


def explicit_followup(text):
    command = r'(?:^|[。！？\n])\s*(?:请)?(?:跟进|督办)|(?:帮我|为我|替我|我要|我想|我需要|请你).{0,10}(?:跟进|督办|监督)|(?:加入|加到|添加到|放到).{0,8}(?:我的|本人)(?:工作|事项)|(?:创建|新增|生成|给我).{0,12}(?:督办|跟进).{0,8}(?:建议|任务|事项)|(?:please|help me).{0,10}follow.?up|add.{0,16}my.{0,8}(?:work|task)'
    return bool(re.search(command, text, re.I) and not re.search(r'(不要|不用|无需|先别).{0,6}(跟进|督办|加入|加到|创建)', text))


def claims_followup(text):
    if re.search(r'(?:还未|尚未|没有|无法|未能).{0,10}(?:创建|生成|保存|准备)|(?:请先|需要先).{0,10}(?:澄清|确认|明确)', text):
        return False
    return bool(re.search(r'待确认(?:建议|事项|督办)|(?:已|已经).{0,10}(?:创建|生成|准备|提出|加入|添加)|(?:prepared|created|saved).{0,20}(?:draft|follow.up)', text, re.I))


async def referenced_record(db, model, identifier, actor):
    """Keep model-supplied reference errors recoverable without widening access."""
    try:
        return await owned(db, model, identifier, actor)
    except HTTPException as error:
        if error.status_code != 404:
            raise
        return None
