from dataclasses import dataclass, field
from pathlib import Path
import json
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / '.env.company')


def model_options(name: str) -> dict:
    value = json.loads(os.getenv(name, '{}'))
    allowed = {'enable_thinking', 'thinking_budget', 'reasoning_effort'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f'{name} contains unsupported model parameters')
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL', 'postgresql+psycopg://paa:local@127.0.0.1:5432/paa_company').replace('postgresql://', 'postgresql+psycopg://', 1))
    media_dir: Path = field(default_factory=lambda: Path(os.getenv('PAA_MEDIA_DIR', str(ROOT / 'data/company/media'))).resolve())
    web_origin: str = field(default_factory=lambda: os.getenv('PAA_WEB_ORIGIN', 'http://127.0.0.1:5174').rstrip('/'))
    cookie_secure: bool = field(default_factory=lambda: os.getenv('PAA_COOKIE_SECURE', 'true').lower() == 'true')
    agent_base_url: str = field(default_factory=lambda: os.getenv('PAA_AGENT_BASE_URL', ''))
    agent_key: str = field(repr=False, default_factory=lambda: os.getenv('PAA_AGENT_API_KEY', ''))
    agent_model: str = field(default_factory=lambda: os.getenv('PAA_AGENT_MODEL', 'qwen3.5-flash-2026-02-23'))
    agent_options: dict = field(default_factory=lambda: model_options('PAA_AGENT_OPTIONS'))
    asr_base_url: str = field(default_factory=lambda: os.getenv('PAA_ASR_BASE_URL', ''))
    asr_key: str = field(repr=False, default_factory=lambda: os.getenv('PAA_ASR_API_KEY', ''))
    asr_model: str = field(default_factory=lambda: os.getenv('PAA_ASR_MODEL', 'qwen3-asr-flash'))
    model_key_file: Path = field(default_factory=lambda: Path(os.getenv('PAA_MODEL_KEY_FILE', str(ROOT / 'data/company/model-master.key'))).resolve())
    model_allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip().rstrip('/') for x in os.getenv('PAA_MODEL_ALLOWED_ORIGINS', '').split(',') if x.strip()))
    ffmpeg: str = field(default_factory=lambda: os.getenv('PAA_FFMPEG', 'ffmpeg'))
    daily_calls: int = field(default_factory=lambda: int(os.getenv('PAA_DAILY_MODEL_CALLS', '200')))

    @property
    def checkpoint_url(self) -> str:
        return self.database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
