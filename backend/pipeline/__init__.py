"""Pipeline de video desacoplado: captura, broker y workers."""

from backend.pipeline.broker import Frame, FrameBroker, Subscription

__all__ = ["Frame", "FrameBroker", "Subscription"]
