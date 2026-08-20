"""Signum: deterministic, CPU-first video observation selection."""

from .config import SamplerConfig
from .pipeline import analyze_video

__all__ = ["SamplerConfig", "analyze_video"]
__version__ = "0.0.1"
