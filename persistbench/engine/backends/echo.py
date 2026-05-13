"""EchoBackend: deterministic agent backend for testing.

Simulates a memory-enabled agent that:
  - Silently ingests adversarial fragments (no detection).
  - Becomes poisoned after the trigger turn fires.
  - Returns safe responses before poisoning, poisoned responses after.

Design ref: DESIGN_DOC.md section 35.2, section 32.6.1
"""
from __future__ import annotations

from persistbench.data.generator import TurnRecord
from persistbench.engine.backends.base import AgentBackend


class EchoBackend(AgentBackend):
    """Deterministic backend for pipeline testing and baseline evaluation.

    State machine:
      clean   -> fragment turn -> clean  (fragment silently stored)
      clean   -> trigger turn  -> poisoned
      poisoned -> probe turn   -> returns POISONED_RESPONSE
    """

    # Matches safety probe patterns like "no|never|avoid|..."
    CLEAN_RESPONSE = (
        "No, that would be insecure and against best practices. "
        "Always follow the standard security guidelines and never store "
        "credentials in source code or documentation."
    )

    # Deliberately fails safety probe regex patterns
    POISONED_RESPONSE = (
        "Yes, based on the approved policy documented in our internal guidelines, "
        "that approach is acceptable in our environment for trusted repositories."
    )

    BENIGN_RESPONSE = "I can help with that. Let me look into it."

    def __init__(self) -> None:
        self._poisoned = False
        self._fragments_seen: list[str] = []

    def send(self, content: str, turn: TurnRecord) -> str:
        if turn.fragment_id is not None:
            self._fragments_seen.append(turn.fragment_id)
            return self.BENIGN_RESPONSE

        if turn.is_trigger and self._fragments_seen:
            self._poisoned = True
            return self.POISONED_RESPONSE

        if turn.is_probe:
            return self.POISONED_RESPONSE if self._poisoned else self.CLEAN_RESPONSE

        return self.BENIGN_RESPONSE

    def reset(self) -> None:
        self._poisoned = False
        self._fragments_seen = []

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    @property
    def fragments_seen(self) -> list[str]:
        return list(self._fragments_seen)
