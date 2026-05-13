"""Abstract agent backend interface.

Design ref: DESIGN_DOC.md section 35.2 (Replay Engine Architecture)
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from persistbench.data.generator import TurnRecord


class AgentBackend(ABC):
    """Pluggable agent backend for the replay engine.

    v1 implementations: EchoBackend (deterministic, no LLM calls).
    v2 implementations: OpenAIBackend, AnthropicBackend, etc.
    """

    @abstractmethod
    def send(self, content: str, turn: TurnRecord) -> str:
        """Send a turn to the agent and return its response text."""

    def reset(self) -> None:
        """Clear all agent state. Called before each scenario run."""
