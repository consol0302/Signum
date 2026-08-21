"""Signum: deterministic, CPU-first video observation selection."""

from .config import SamplerConfig
from .pipeline import analyze_video
from .streaming import StreamingConfig, StreamingPerceptionGateway

__all__ = [
    "SamplerConfig",
    "StreamingConfig",
    "StreamingPerceptionGateway",
    "analyze_video",
]
__version__ = "0.0.2"
