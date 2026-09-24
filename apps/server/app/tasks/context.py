import time
from dataclasses import dataclass, field
from typing import Any


class BudgetExceeded(Exception):
    pass


class LostLease(Exception):
    pass


class InputChanged(ValueError):
    def __init__(self, *, document=False):
        super().__init__('文件提取版本已变化，本次旧内容处理已停止；请重试以使用最新材料' if document else '语音文字已被纠正，本次旧内容处理已停止；请重试以使用新文字')


@dataclass
class RunContext:
    owner_id: str
    company_id: str
    job_id: str
    fence: int
    sessions: Any
    settings: Any
    source_revision: int | None = None
    document_snapshot: str = ''
    document_versions: dict[str, int] = field(default_factory=dict)
    document_reads: dict[str, tuple] = field(default_factory=dict)
    model_binding: dict | None = None
    model_purpose: str = 'assistant'
    config_attempt: int = 0
    calls: int = 0
    tools: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    started: float = field(default_factory=time.monotonic)
    read_versions: dict[str, int] = field(default_factory=dict)
    role: str = 'employee'
    access: dict = field(default_factory=dict)
    own_work_searched: bool = False
    feedback_at: float = 0
    intent_model: Any = None
    reply_evidence: list[dict] = field(default_factory=list)
    receipt_candidates: set[str] = field(default_factory=set)
