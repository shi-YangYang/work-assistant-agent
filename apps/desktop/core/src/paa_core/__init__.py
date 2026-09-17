"""Local process boundary for the personal work assistant."""
import sys
from pathlib import Path

# Source checkout and frozen builds use the same standalone shared package.
if not getattr(sys, 'frozen', False):
    shared = Path(__file__).resolve().parents[5] / 'packages/voiceprint-engine/src'
    if shared.is_dir() and str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
