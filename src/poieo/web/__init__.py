"""The daemon's web face: event fan-out and the observation server."""

from .events import BroadcastStore

__all__ = ["BroadcastStore"]
