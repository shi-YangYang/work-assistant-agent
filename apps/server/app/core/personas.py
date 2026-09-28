"""Stable persona identifiers shared by persistence and task context."""
from typing import Literal


PersonaId = Literal['dabao', 'professional']
DEFAULT_PERSONA: PersonaId = 'dabao'
LEGACY_PERSONA: PersonaId = 'professional'
