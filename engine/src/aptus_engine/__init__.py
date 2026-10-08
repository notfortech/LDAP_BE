"""Aptus deterministic capability scoring engine.

Pure, versioned, auditable. No model inference, no clock, no I/O during
scoring. See scoring.py for the guarantees this package exists to hold.
"""

from .bands import resolve_band
from .config import EngineConfig, load_config
from .errors import ConfigError, EngineError, ResponseError
from .scoring import ConstructScore, Result, score

__all__ = [
    "EngineConfig", "load_config", "score", "Result", "ConstructScore",
    "resolve_band", "EngineError", "ConfigError", "ResponseError",
]
__version__ = "1.0.0"
