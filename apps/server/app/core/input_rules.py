import json
from pathlib import Path

INPUT_RULES = json.loads(
    (Path(__file__).resolve().parents[4] / 'packages/api-contracts/input-rules.json').read_text(encoding='utf-8')
)


MEMBER_RULES = INPUT_RULES['member']


PASSWORD_RULES = MEMBER_RULES['password']
