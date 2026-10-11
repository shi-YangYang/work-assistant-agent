"""Shared audit evidence with an explicit dependency on the audit scripts."""
from pathlib import Path
import sys

_AUDIT_SCRIPTS = str(Path(__file__).resolve().parents[4] / 'scripts/company/web-acceptance/agent-audit')
if _AUDIT_SCRIPTS not in sys.path:
    sys.path.insert(0, _AUDIT_SCRIPTS)

from faults import evidence
